# -*- coding: utf-8 -*-
"""取得から画面用データの書き出しまでの流れ。

保存先の分担:
  settings/*   画面（利用者）が書く。コレクターは読むだけ
  state/*      コレクターが書く作業用データ
  candidates/* コレクターが書く。商品ごとの競合候補
  cats/*       コレクターが書く。カテゴリごとの日々の順位
  views/*      コレクターが書く。画面はここを読むだけで表示できる

ログには件数とトークン数だけを書く（公開リポジトリのため、商品名や ASIN は書かない）。
"""
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import dashboard, parse
from .config import DEFAULT_RESEARCH, DEFAULT_THRESHOLDS, MARKET_COHERENCE, MARKET_RULES
from .keepa import KeepaError
from .parse import CSV_NEW, CSV_RATING, CSV_REVIEWS, CSV_SALES, JST

SEV_ORDER = {'crit': 0, 'serious': 1, 'warn': 2, 'good': 3, 'info': 4}
HISTORY_DAYS = 730      # 月別販売数を24か月分表示するため、履歴は2年分を取る（トークンは変わらない）


def _median(vals):
    v = sorted(vals)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def _mean(values):
    vals = [v for v in values if isinstance(v, (int, float)) and v > 0]
    return round(sum(vals) / len(vals)) if vals else None


# 予約実行の回（日本時間）。この時刻を過ぎて、まだ取得していなければ実行する。
DAILY_FROM = (2, 0)
PRICE_SLOTS = ((10, 0), (14, 0), (19, 0))
MAX_DAILY_TRIES = 3
RESEARCH_POOL = 300          # リサーチで候補として取る件数の上限
MARKET_TOP = 20              # 市場 1 つにつき評価する上位商品の数
MARKET_COMPARE = 6           # 比較用に調べる市場の数
MARKET_KEYWORD_POOL = 30     # キーワードで集める市場 1 つにつき調べる商品の数
MARKET_HISTORY_DAYS = 400    # 最盛期を見るために取る履歴の日数（トークンは変わらない）


def _parse_time(iso):
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return t.astimezone(JST) if t.tzinfo else t.replace(tzinfo=JST)


def mark_auto(items, limit=2):
    """利用者が選ぶまで自動で監視する候補に印を付ける。推奨のうち、いま出品があるものの上位。

    出品がない商品（販売終了の古い出品など）を自動で選ぶと、在庫切れの通知が意味を持たなくなるため除く。
    """
    n = 0
    for it in items:
        ok = it.get('group') == 'rec' and it.get('price') is not None and n < limit
        it['auto'] = ok
        n += 1 if ok else 0
    return items

def mark_picks(picks, limit=2):
    """提案の中から、利用者が選ぶまで自動で監視するものに印を付ける。提案の順で、いま出品があるものの上位。"""
    n = 0
    for it in picks:
        ok = it.get('price') is not None and n < limit
        it['auto'] = ok
        n += 1 if ok else 0
    return picks


class Run:
    def __init__(self, store, keepa, cfg, now=None, log=print, dash_fetch=None):
        self.store, self.keepa, self.cfg, self.log = store, keepa, cfg, log
        self.now = now or datetime.now(JST)
        self._t0 = time.monotonic()
        self.today = self.now.date()
        self.iso = self.today.strftime('%Y-%m-%d')
        self.dash_fetch = dash_fetch
        self.warnings = []
        self.own, self.new_own = {}, []
        self.families, self.own_products = {}, {}
        self.comp_products, self.comp_items = {}, []
        self.candidates = {}
        self.cat_items = []
        self._rankings = {}
        self._brief_cache = {}
        self.s_fam, self.excluded_brands, self.th, self.research_params = {}, set(), dict(DEFAULT_THRESHOLDS), dict(DEFAULT_RESEARCH)

    # ------------------------------------------------------------------ 設定
    def load_settings(self):
        self.s_fam = (self.store.get('settings/families') or {}).get('items') or {}
        self.excluded_brands = {str(b).strip().lower() for b in ((self.store.get('settings/brands') or {}).get('excluded') or []) if str(b).strip()}
        self.th = dict(DEFAULT_THRESHOLDS)
        self.th.update({k: v for k, v in (self.store.get('settings/thresholds') or {}).items() if k in DEFAULT_THRESHOLDS})
        self.research_params = dict(DEFAULT_RESEARCH)
        self.research_params.update({k: v for k, v in (self.store.get('settings/research') or {}).items() if k in DEFAULT_RESEARCH})

    def load_state(self):
        """前回の実行結果を読み込む（自社カタログを取り直さないジョブ用）。"""
        self.own = (self.store.get('state/own') or {}).get('items') or {}
        self.families = (self.store.get('state/families') or {}).get('items') or {}

    def load_candidates(self):
        self.candidates = self.store.list('candidates')
        for doc in self.candidates.values():
            mark_auto(doc.get('items') or [])
            mark_picks(doc.get('picks') or [])

    # ------------------------------------------------------------------ 自社商品の自動追加
    def sync_own(self):
        prev = (self.store.get('state/own') or {}).get('items') or {}
        try:
            kw = {'fetch': self.dash_fetch} if self.dash_fetch else {}
            rows = dashboard.fetch_rows(self.cfg.dashboard_project, self.cfg.accounts, self.cfg.dashboard_api_key, **kw)
        except dashboard.DashboardError as e:
            self.warnings.append(str(e) + ' 前回の一覧を使いました。')
            self.own = prev
            return
        merged = dashboard.merge_rows(rows)
        if not merged:
            self.warnings.append('ダッシュボードの在庫データが空でした。前回の一覧を使いました。')
            self.own = prev
            return
        out, new = {}, []
        for asin, e in merged.items():
            old = prev.get(asin) or {}
            if not old and prev:
                new.append(asin)
            out[asin] = {'account': e['account'], 'sku': e['sku'], 'name': e['name'], 'qty': e['qty'], 'total': e['total'],
                         'inbound': e['inbound'], 'active': e['active'],
                         'firstSeen': old.get('firstSeen') or self.iso, 'lastSeen': self.iso}
        for asin, old in prev.items():
            if asin not in out:                      # 一覧から消えた商品は削除せず停止にする
                o = dict(old)
                o['active'], o['gone'] = False, True
                out[asin] = o
        self.store.set('state/own', {'updatedAt': self.now.isoformat(), 'items': out})
        self.own, self.new_own = out, new
        self.log('自社商品: {} 件（監視対象 {} / 新規 {}）'.format(len(out), sum(1 for e in out.values() if e.get('active')), len(new)))

    # ------------------------------------------------------------------ 自社カタログ
    def own_catalog(self):
        active = sorted(a for a, e in self.own.items() if e.get('active'))
        prods = self.keepa.products(active, history=True, days=HISTORY_DAYS, rating=True, label='自社カタログ')
        self.own_products = prods
        prev = (self.store.get('state/families') or {}).get('items') or {}
        groups = defaultdict(list)
        for asin, p in prods.items():
            groups[p.get('parentAsin') or asin].append(p)

        def stock(p):
            e = self.own.get(p['asin']) or {}
            return (e.get('total') or 0) + (e.get('inbound') or 0)

        fams = {}
        for parent, members in groups.items():
            old = prev.get(parent) or {}
            priced = [m for m in members if parse.current(m, CSV_NEW) is not None]
            keep = [m for m in priced if m['asin'] == old.get('rep')]
            rep = keep[0] if keep else max(priced or members, key=stock)   # 代表は前回と同じものを優先
            acct = Counter((self.own.get(m['asin']) or {}).get('account') for m in members).most_common(1)[0][0]
            tree = [{'id': c.get('catId'), 'name': c.get('name')} for c in (rep.get('categoryTree') or [])]
            fp = parse.fingerprint(rep)
            changed_at, what = old.get('changedAt'), old.get('changeWhat')
            if old.get('fp') and old.get('rep') == rep['asin']:
                diff = [label for key, label in (('title', '商品タイトル'), ('image', 'メイン画像')) if old['fp'].get(key) != fp[key]]
                if diff:
                    changed_at, what = self.iso, 'と'.join(diff)
            asins = sorted(m['asin'] for m in members)
            fams[parent] = {
                'account': acct, 'name': parse.short_name(rep.get('title'), rep.get('brand')),
                'title': (rep.get('title') or '')[:120], 'brand': rep.get('brand') or '', 'rep': rep['asin'],
                'asins': asins, 'variations': parse.variation_asins(rep) or asins,
                'cat': tree[-1] if tree else None, 'cats': tree,
                'fp': fp, 'changedAt': changed_at, 'changeWhat': what,
                'firstSeen': old.get('firstSeen') or self.iso,
            }
        parse.distinguish_names(fams)
        self.store.set('state/families', {'updatedAt': self.now.isoformat(), 'items': fams})
        self.families = fams
        self.log('自社カタログ: {} ASIN を取得、{} 商品にまとめました'.format(len(prods), len(fams)))

    def own_status(self, it):
        th = self.th
        if it.get('rating') is not None and it.get('rating30') is not None and it['rating30'] - it['rating'] >= th['ratingDrop'] - 1e-9:
            return {'sev': 'crit', 'label': '評価低下'}
        # ランキングは日々大きく動くので使わない。Amazon が表示する月間の購入数を、30日前の表示と比べる
        before = it.get('sold30') or 0
        if before >= th['soldMin'] and (it.get('sold') or 0) <= before * (1 - th['soldDropPct'] / 100.0):
            return {'sev': 'serious', 'label': '販売数減少'}
        if it.get('changedAt') and self._days_since(it['changedAt']) <= th['pageChangeDays']:
            return {'sev': 'warn', 'label': 'ページ変更'}
        if it.get('oos'):
            return {'sev': 'warn', 'label': '出品なしあり'}
        return {'sev': 'good', 'label': '正常'}

    def _days_since(self, iso):
        try:
            return (self.today - datetime.strptime(iso, '%Y-%m-%d').date()).days
        except (TypeError, ValueError):
            return 9999

    def own_view(self):
        items = []
        for parent, fam in self.families.items():
            rep = self.own_products.get(fam['rep'])
            if not rep:
                continue
            members = [self.own_products[a] for a in fam['asins'] if a in self.own_products]
            b = parse.brief(rep)
            rank_pts, rating_pts, rev_pts = parse.changes(rep, CSV_SALES), parse.changes(rep, CSV_RATING), parse.changes(rep, CSV_REVIEWS)
            days = int(self.th['compareDays'])
            rating_old = parse.value_days_ago(rating_pts, days, self.today)
            rank_long = parse.daily(rank_pts, days + 4, self.today)
            rank_hist = rank_long[-30:]
            prices = [v for v in (parse.current(m, CSV_NEW) for m in members) if v is not None]
            oos = [m['asin'] for m in members if parse.current(m, CSV_NEW) is None and (self.own.get(m['asin']) or {}).get('qty', 0) > 0]
            # 月間の購入数は色・サイズごとに表示されることがあるので、いちばん多い色・サイズの値で見る
            sold_now = max((m.get('monthlySold') for m in members if isinstance(m.get('monthlySold'), int) and m['monthlySold'] > 0), default=None)
            sold_old = [v for v in (parse.sold_at(m, self.now - timedelta(days=days)) for m in members) if v is not None]
            it = {
                'parent': parent, 'acct': fam['account'], 'name': fam['name'], 'title': fam['title'], 'rep': fam['rep'],
                'image': b['image'], 'nvar': len(fam['asins']), 'cat': (fam.get('cat') or {}).get('name'),
                'price': b['price'], 'priceMin': min(prices) if prices else None, 'priceMax': max(prices) if prices else None,
                'priceHist': parse.compress(parse.daily(parse.changes(rep, CSV_NEW), 90, self.today)),
                'cmpDays': days,
                'rank': b['rank'], 'rankNow3': _mean(rank_long[-3:]), 'rank30': _mean(rank_long[:3]), 'rankHist': rank_hist,
                'rating': b['rating'], 'rating30': (rating_old / 10.0) if rating_old is not None and rating_old >= 0 else None,
                'reviews': b['reviews'], 'reviews30': parse.value_days_ago(rev_pts, days, self.today),
                'sold': sold_now, 'sold30': max(sold_old) if sold_old else None,
                'coupon': b['coupon'], 'deal': b['deal'],
                'changedAt': fam.get('changedAt'), 'changeWhat': fam.get('changeWhat'), 'oos': len(oos),
            }
            it['status'] = self.own_status(it)
            items.append(it)
        items.sort(key=lambda x: (SEV_ORDER[x['status']['sev']], x['acct'] or '', x['name']))
        return items

    # ------------------------------------------------------------------ 競合
    def effective_competitors(self, parent):
        """[(asin, manual, auto)]。利用者が選んだものがあればそれを、なければ自動選択を使う。"""
        comps = (self.s_fam.get(parent) or {}).get('competitors')
        if comps:
            return [(a, bool(c.get('manual')), False) for a, c in sorted(comps.items()) if c and c.get('on')]
        cand = self.candidates.get(parent)
        if cand:                                      # 提案があれば提案の上位、なければ自動の候補の上位
            return [(i['asin'], False, True) for i in (cand.get('picks') or cand.get('items') or []) if i.get('auto')]
        return []

    def competitors(self, days=HISTORY_DAYS, rating=True, previous=None):
        pairs = [(parent, a, m, au) for parent in self.families for a, m, au in self.effective_competitors(parent)]
        need = sorted({a for _, a, _, _ in pairs if a not in self.comp_products})
        if need:
            self.comp_products.update(self.keepa.products(need, history=True, days=days, rating=rating, label='競合'))
        prev = {(i.get('parent'), i.get('asin')): i for i in (previous or [])}
        items = []
        for parent, asin, manual, auto in pairs:
            fam = self.families[parent]
            base = {'asin': asin, 'parent': parent, 'acct': fam['account'], 'ownName': fam['name'], 'manual': manual, 'auto': auto}
            p = self.comp_products.get(asin)
            if not p:
                base.update({'pending': True, 'title': '', 'brand': '', 'price': None, 'stock': 'unknown'})
                items.append(base)
                continue
            b = parse.brief(p)
            price_pts = parse.changes(p, CSV_NEW)
            d90 = parse.daily(price_pts, 90, self.today)
            before = parse.value_at(price_pts, self.now - timedelta(hours=24))      # 24時間前の価格と比べる
            prev_price = before if before and before > 0 else None
            out = b['price'] is None
            old = prev.get((parent, asin)) or {}
            base.update({
                'title': b['title'][:80], 'brand': b['brand'], 'image': b['image'],
                'price': b['price'], 'prev': prev_price, 'hist': parse.compress(d90),
                'coupon': b['coupon'], 'couponNew': parse.coupon_started_recently(p, self.now), 'deal': b['deal'],
                'stock': 'out' if out else 'in', 'outDays': parse.out_of_stock_days(p, self.today) if out else 0,
                'strip': ''.join('2' if v == -1 else '0' for v in d90[-30:]),
                'rating': b['rating'] if b['rating'] is not None else old.get('rating'),
                'reviews': b['reviews'] if b['reviews'] is not None else old.get('reviews'),
                'sold': b['sold'] if b['sold'] is not None else old.get('sold'),
            })
            items.append(base)
        self.comp_items = items
        self.log('競合: {} 件（商品との組み合わせ {} 件）'.format(len({a for _, a, _, _ in pairs}), len(items)))
        return items

    # ------------------------------------------------------------------ カテゴリ順位
    def ranking(self, cat_id):
        if cat_id not in self._rankings:
            self._rankings[cat_id] = self.keepa.bestsellers(cat_id, label='カテゴリ順位')
        return self._rankings[cat_id]

    def ranking_for(self, fam):
        for cat in list(reversed(fam.get('cats') or []))[:2]:      # いちばん細かいカテゴリから。無ければ1つ上
            if cat.get('id'):
                r = self.ranking(cat['id'])
                if r:
                    return r, cat
        return [], None

    def categories(self):
        by_cat = defaultdict(list)
        for parent, fam in self.families.items():
            if fam.get('cat') and fam['cat'].get('id'):
                by_cat[fam['cat']['id']].append(parent)
        selected = sorted(by_cat, key=lambda c: (-len(by_cat[c]), c))[:self.cfg.max_categories]
        names = (self.store.get('state/names') or {}).get('items') or {}
        own_by_asin = {a: parent for parent, f in self.families.items() for a in set(f['variations']) | set(f['asins'])}
        staged, unknown = [], set()
        limit_day = (self.today - timedelta(days=35)).strftime('%Y-%m-%d')
        for cat_id in selected:
            ranking = self.ranking(cat_id)
            if not ranking:
                continue
            index = {a: i + 1 for i, a in enumerate(ranking)}
            cat_name = self.families[by_cat[cat_id][0]]['cat']['name']
            doc = self.store.get('cats/{}'.format(cat_id)) or {'name': cat_name, 'top': {}, 'pos': {}}
            doc['name'] = cat_name
            tracked, comp_by_asin = {}, {}
            for parent in by_cat[cat_id]:
                fam = self.families[parent]
                tracked['own:' + parent] = min((index[a] for a in set(fam['variations']) | set(fam['asins']) if a in index), default=None)
                for asin, _, _ in self.effective_competitors(parent):
                    p = self.comp_products.get(asin)
                    variants = set(parse.variation_asins(p) if p else []) | {asin}
                    tracked[asin] = min((index[a] for a in variants if a in index), default=None)
                    for a in variants:
                        comp_by_asin[a] = asin
            doc['top'][self.iso] = ranking[:30]
            doc['pos'][self.iso] = tracked
            for key in ('top', 'pos'):
                doc[key] = {d: v for d, v in doc[key].items() if d >= limit_day}
            self.store.set('cats/{}'.format(cat_id), doc)
            for a in ranking[:10]:
                if a not in own_by_asin and a not in comp_by_asin and a not in names and a not in self.comp_products:
                    unknown.add(a)
            staged.append((cat_id, doc, ranking, by_cat[cat_id], comp_by_asin))
        if unknown:                                   # 上位10件の商品名（初回だけ取得し、以後は控えを使う）
            for a, p in self.keepa.products(sorted(unknown), history=False, rating=False, label='カテゴリ上位の商品名').items():
                names[a] = {'t': (p.get('title') or '')[:80], 'b': p.get('brand') or ''}
            if len(names) > 3000:
                names = dict(list(names.items())[-3000:])
            self.store.set('state/names', {'updatedAt': self.now.isoformat(), 'items': names})

        d7 = (self.today - timedelta(days=7)).strftime('%Y-%m-%d')
        days30 = [(self.today - timedelta(days=29 - i)).strftime('%Y-%m-%d') for i in range(30)]
        items = []
        for cat_id, doc, ranking, parents, comp_by_asin in staged:
            past_days = sorted(d for d in doc['top'] if d < self.iso)
            old_days = [d for d in past_days if d <= d7]
            old7 = doc['top'][old_days[-1]] if old_days else None
            seen = set()
            for d in past_days:
                seen.update(doc['top'][d])
            top = []
            for r, a in enumerate(ranking[:10], 1):
                if a in own_by_asin:
                    kind, title, brand = 'own', self.families[own_by_asin[a]]['name'], self.families[own_by_asin[a]]['brand']
                else:
                    cp = self.comp_products.get(comp_by_asin.get(a) or a)
                    nm = names.get(a) or {}
                    title = (cp.get('title') if cp else nm.get('t')) or a
                    brand = (cp.get('brand') if cp else nm.get('b')) or ''
                    kind = 'comp' if a in comp_by_asin else ('new' if old_days and a not in seen else 'other')
                p7 = (old7.index(a) + 1) if old7 and a in old7 else None
                top.append({'r': r, 'asin': a, 'title': title[:80], 'brand': brand, 'p7': p7, 'kind': kind, 'hasOld': bool(old7)})
            tracks = []
            for key in doc['pos'].get(self.iso, {}):
                if key.startswith('own:'):
                    fam = self.families.get(key[4:])
                    name, kind = (fam['name'] if fam else key[4:]), 'own'
                else:
                    cp = self.comp_products.get(key)
                    name, kind = ((cp.get('title') or key)[:40] if cp else key), 'comp'
                tracks.append({'key': key, 'name': name, 'kind': kind,
                               'hist': [(doc['pos'].get(d) or {}).get(key) for d in days30]})
            items.append({'catId': cat_id, 'name': doc['name'], 'size': len(ranking), 'parents': parents,
                          'accts': sorted({self.families[p]['account'] for p in parents}),
                          'top': top, 'tracks': tracks, 'days': len(doc['top'])})
        self._name_same_categories(items)
        self.cat_items = items
        self.log('カテゴリ順位: {} カテゴリ'.format(len(items)))
        return items

    def _name_same_categories(self, items):
        """同じ名前のカテゴリ（レディースとメンズの「トートバッグ」など）に、区別できる上位カテゴリ名を付ける。"""
        groups = defaultdict(list)
        for it in items:
            groups[it['name']].append(it)
        for name, group in groups.items():
            if len(group) < 2:
                continue
            paths = []
            for it in group:
                path = [c.get('name') or '' for c in (self.families[it['parents'][0]].get('cats') or [])]
                ids = [c.get('id') for c in (self.families[it['parents'][0]].get('cats') or [])]
                paths.append(path[:ids.index(it['catId'])] if it['catId'] in ids else path[:-1])
            for it, path in zip(group, paths):
                label = next((path[-k] for k in range(1, len(path) + 1)
                              if len({(p[-k] if len(p) >= k else '') for p in paths}) == len(paths)), None)
                it['name'] = '{}（{}）'.format(name, label or ' > '.join(path) or it['catId'])

    # ------------------------------------------------------------------ 競合候補
    def build_candidates(self, limit=0):
        own_all = set(self.own)
        own_brands = {f['brand'].strip().lower() for f in self.families.values() if f.get('brand')}
        for f in self.families.values():
            own_all.update(f['variations'])
        todo = []
        for parent in sorted(self.families, key=lambda k: (self.families[k].get('firstSeen') or '', k), reverse=True):
            cand = self.candidates.get(parent)
            regen = (self.s_fam.get(parent) or {}).get('regenAt')
            if not cand or (regen and regen > (cand.get('updatedAt') or '')):
                todo.append(parent)
        if limit:
            todo = todo[:limit]
        built = 0
        for parent in todo:
            fam = self.families[parent]
            try:
                doc = self._candidates_for(parent, fam, own_all, own_brands)
            except KeepaError as e:
                self.warnings.append('競合候補の作成を途中で止めました（残り {} 商品）。次回の実行で続きを作ります。'.format(len(todo) - built))
                self.log('競合候補: 中断（{}）'.format(e))
                break
            prev = self.candidates.get(parent) or {}
            if prev.get('picks'):                     # 候補を作り直しても、取り込んだ提案は残す
                doc['picks'], doc['picksAt'] = prev['picks'], prev.get('picksAt') or ''
            self.store.set('candidates/{}'.format(parent), doc)
            self.candidates[parent] = doc
            built += 1
        self.log('競合候補: {} 商品分を作成（対象 {}）'.format(built, len(todo)))
        return built

    def build_picks(self):
        """画面から取り込んだ競合・ベンチマークの提案（settings/families の picks）に、商品名や価格を付けて
        candidates/{親ASIN} の picks に保存する。提案が変わった商品だけ取得する。"""
        own_all = set(self.own)
        for f in self.families.values():
            own_all.update(f['variations'])
        todo = []
        for parent in sorted(self.families):
            s = self.s_fam.get(parent) or {}
            picks = [x for x in (s.get('picks') or []) if isinstance(x, dict) and x.get('asin') and x['asin'] not in own_all]
            if picks and (self.candidates.get(parent) or {}).get('picksAt') != (s.get('picksAt') or ''):
                todo.append((parent, picks, s.get('picksAt') or ''))
        if not todo:
            return 0
        need = sorted({x['asin'] for _, picks, _ in todo for x in picks if x['asin'] not in self._brief_cache})
        try:
            if need:
                self._brief_cache.update(self.keepa.products(need, history=False, rating=True, label='競合の提案'))
        except KeepaError as e:
            self.warnings.append('競合の提案の取得を途中で止めました。次回の実行で続きを取得します。')
            self.log('競合の提案: 中断（{}）'.format(e))
            return 0
        for parent, picks, stamp in todo:
            fam = self.families[parent]
            doc = self.candidates.get(parent) or {'updatedAt': self.now.isoformat(), 'kw': [], 'terms': [], 'cat': fam.get('cat'), 'pool': 0, 'items': []}
            out, seen = [], set()
            for x in picks:
                a = x['asin']
                if a in seen:
                    continue
                seen.add(a)
                p = self._brief_cache.get(a)
                b = parse.brief(p) if p else {}
                out.append({'asin': a, 'title': (b.get('title') or '')[:80], 'brand': b.get('brand') or '', 'image': b.get('image'),
                            'price': b.get('price'), 'rating': b.get('rating'), 'reviews': b.get('reviews'), 'sold': b.get('sold'),
                            'why': str(x.get('why') or '')[:120], 'missing': not p, 'auto': False})
            doc['picks'], doc['picksAt'] = mark_picks(out), stamp
            self.store.set('candidates/{}'.format(parent), doc)
            self.candidates[parent] = doc
        self.log('競合の提案: {} 商品分を反映（提案 {} 件）'.format(len(todo), sum(len(p) for _, p, _ in todo)))
        return len(todo)

    def _candidates_for(self, parent, fam, own_all, own_brands):
        ranking, cat = self.ranking_for(fam)
        picks = [(i + 1, a) for i, a in enumerate(ranking) if a not in own_all][:self.cfg.category_top]
        pool = {}

        def add(p, source, pos):
            a = p.get('asin')
            brand = (p.get('brand') or '').strip().lower()
            if not a or a in own_all or brand in own_brands or brand in self.excluded_brands:
                return
            d = pool.get(a)
            if d is None:
                d = pool[a] = parse.brief(p)
                d['catPos'], d['searchPos'] = None, None
            d[source] = pos if d[source] is None else min(d[source], pos)

        # 同じカテゴリの商品は 1 回の実行の中で使い回す（同じカテゴリに自社商品が複数あるため）
        missing = [a for _, a in picks if a not in self._brief_cache]
        if missing:
            self._brief_cache.update(self.keepa.products(missing, history=False, rating=True, label='候補（カテゴリ上位）'))
        top = {a: self._brief_cache[a] for _, a in picks if a in self._brief_cache}
        for pos, a in picks:
            if a in top:
                add(top[a], 'catPos', pos)
        s = self.s_fam.get(parent) or {}
        kw = [k for k in (s.get('kw') or []) if k] or parse.auto_keywords(fam['title'], fam['brand'], [p.get('title') for p in top.values()])
        terms = [t for t in (s.get('terms') or []) if t] or ([' '.join(kw[:2])] if kw else [])
        for term in terms[:3]:
            for i, p in enumerate(self.keepa.search(term, label='候補（検索）'), 1):
                add(p, 'searchPos', i)

        max_offers = self.th['maxOffersForPb']
        seen, uniq = set(), []
        for d in sorted(pool.values(), key=lambda x: x['catPos'] if x['catPos'] is not None else 1000 + (x['searchPos'] or 99)):
            if d['parent'] in seen:                    # 色・サイズ違いは 1 件にまとめる
                continue
            seen.add(d['parent'])
            match = any(k in d['title'] for k in kw)
            why = []
            if d['amazonSells']:
                why.append('Amazonが販売')
            if d['offers'] is not None and d['offers'] > max_offers:
                why.append('出品 {}社'.format(d['offers']))
            d['group'] = 'other' if not match else ('big' if why else 'rec')
            d['why'] = '・'.join(why)
            uniq.append(d)
        keep = [d for d in uniq if d['group'] == 'rec'][:15] + [d for d in uniq if d['group'] == 'big'][:10] + [d for d in uniq if d['group'] == 'other'][:10]
        items = []
        for n, d in enumerate(keep):
            items.append({'asin': d['asin'], 'title': d['title'][:80], 'brand': d['brand'], 'image': d['image'], 'price': d['price'],
                          'rating': d['rating'], 'reviews': d['reviews'], 'sold': d['sold'], 'catPos': d['catPos'], 'searchPos': d['searchPos'],
                          'group': d['group'], 'why': d['why'], 'auto': False})
        mark_auto(items)
        return {'updatedAt': self.now.isoformat(), 'kw': kw, 'terms': terms, 'cat': cat, 'pool': len(uniq), 'items': items}

    # ------------------------------------------------------------------ 販売実績
    def sales_view(self):
        months, y, m = [], self.today.year, self.today.month
        for _ in range(24):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            months.append('{:04d}-{:02d}'.format(y, m))
        months.reverse()
        own = {}
        for parent, fam in self.families.items():
            rep = self.own_products.get(fam['rep'])
            if rep:
                own[parent] = parse.month_series(parse.monthly_sold(rep), months)
        comps, dips = {}, {}
        for asin, p in self.comp_products.items():
            comps[asin] = parse.month_series(parse.monthly_sold(p), months)
            d = parse.dips(p, self.today)
            if d:
                dips[asin] = d
        return {'updatedAt': self.now.isoformat(), 'months': months, 'own': own, 'comps': comps, 'dips': dips}

    # ------------------------------------------------------------------ 新商品リサーチ
    def research(self):
        """Amazon 全体から、条件に合う商品を月間販売の多い順に抽出する。

        カテゴリでは絞らない（売れていて勝負できるものなら何でも対象）。本・音楽・ゲームなど、
        作って売る対象にならない大カテゴリだけを外す（settings/research の excludeRoots）。
        """
        prm = self.research_params
        exclude = [x for x in (prm.get('excludeRoots') or []) if x]
        view = {'updatedAt': self._wall().isoformat(), 'params': prm, 'items': [], 'error': None, 'roots': [], 'sort': 'sold'}
        own_brands = {f['brand'].strip().lower() for f in self.families.values() if f.get('brand')}
        own_asins = set(self.own) | {a for f in self.families.values() for a in f['variations']}
        selection = {'current_NEW_gte': prm['priceMin'], 'current_NEW_lte': prm['priceMax'],
                     'monthlySold_gte': prm['soldMin'], 'current_COUNT_REVIEWS_lte': prm['reviewsMax'],
                     'current_SALES_gte': 1, 'current_SALES_lte': prm['rankMax'],
                     'perPage': RESEARCH_POOL, 'page': 0, 'sort': [['monthlySold', 'desc']]}
        try:
            try:
                asins, total = self.keepa.finder(selection)
            except KeepaError:                       # 販売数での並べ替えが使えない場合は、ランキング順で取り直す
                view['sort'] = 'rank'
                asins, total = self.keepa.finder(dict(selection, sort=[['current_SALES', 'asc']]))
        except KeepaError as e:
            view['error'] = '取得に失敗しました: {}'.format(e)
            self.warnings.append('新商品リサーチの取得に失敗しました。')
            return view
        asins = [a for a in asins if a not in own_asins][:RESEARCH_POOL]
        seen, roots = set(), set()
        for i in range(0, len(asins), 100):          # 必要な件数が集まるまで、100 件ずつ詳細を取る
            if len(view['items']) >= prm['limit']:
                break
            try:
                prods = self.keepa.products(asins[i:i + 100], history=False, rating=True, label='リサーチ（商品）')
            except KeepaError as e:
                view['error'] = None if view['items'] else '取得に失敗しました: {}'.format(e)
                self.warnings.append('新商品リサーチの取得を途中で止めました。')
                break
            for a in asins[i:i + 100]:
                p = prods.get(a)
                if not p:
                    continue
                b = parse.brief(p)
                tree = p.get('categoryTree') or []
                root = (tree[0].get('name') or '') if tree else ''
                if root:
                    roots.add(root)
                if any(root == x or (len(x) > 1 and x in root) for x in exclude):
                    continue
                if b['parent'] in seen or b['brand'].strip().lower() in own_brands or b['brand'].strip().lower() in self.excluded_brands:
                    continue
                if b['amazonSells'] or (b['offers'] is not None and b['offers'] > self.th['maxOffersForPb']):
                    continue
                if (b['reviews'] or 0) > prm['reviewsMax'] or (b['rank'] or 10 ** 9) > prm['rankMax']:
                    continue
                seen.add(b['parent'])
                b['listed'] = parse.to_date(p.get('listedSince'))
                b['title'] = b['title'][:80]
                b['root'] = root
                view['items'].append(b)
                if len(view['items']) >= prm['limit']:
                    break
        view['matched'] = total
        view['roots'] = sorted(roots)
        self.log('新商品リサーチ: {} 件'.format(len(view['items'])))
        return view

    # ------------------------------------------------------------------ 市場の評価
    def _market_row(self, p, own_all, own_brands):
        """商品 1 件を、市場の評価に使う値だけにする（履歴つきの商品データは大きいので持ち続けない）。"""
        b = parse.brief(p)
        sold, src = parse.sold_estimate(p)
        peak = parse.peak_sold(p, self.today)
        price = b['price'] or parse.average_price(p)
        listed = p.get('listedSince')
        months = None
        if isinstance(listed, int) and listed > 0:
            months = max(0, int((self.now - parse.to_dt(listed)).days / 30.4))
        brand = (b['brand'] or '').strip()
        return {
            'asin': b['asin'], 'parent': b['parent'], 'title': b['title'][:60], 'brand': brand,
            'price': b['price'], 'sold': sold, 'est': src == 'rank', 'peak': peak,
            'rev': (price or 0) * (sold or 0),                            # いまの推定月商
            'peakRev': (price or 0) * max(sold or 0, peak or 0),         # 最盛期の推定月商
            'reviews': b['reviews'], 'rating': b['rating'], 'months': months,
            'big': bool(b['amazonSells']) or (b['offers'] is not None and b['offers'] > self.th['maxOffersForPb']),
            'amazon': bool(b['amazonSells']),
            'own': b['asin'] in own_all or (brand.lower() in own_brands if brand else False),
        }

    @staticmethod
    def judge(m):
        """狙い目の基準に合わない点を、短い言葉の一覧で返す（空なら狙い目）。"""
        r, out = MARKET_RULES, []
        if m['sizePeak'] < r['sizeMin']:
            out.append('市場が小さい')
        elif m['sizePeak'] > r['sizeMax']:
            out.append('市場が大きすぎる')
        if m['over'] > r['overMax']:
            out.append('大型商品が多い')
        if m['inBand'] < r['inBandMin']:
            out.append('中規模の商品が少ない')
        if m['amazon'] > r['amazonMax']:
            out.append('Amazon本体の販売が多い')
        if m['medReviews'] is not None and m['medReviews'] > r['reviewsMax']:
            out.append('レビューが多い')
        if m['newWinners'] < r['newMin']:
            out.append('新しい成功例がない')
        return out

    def market_item(self, target, rows_by_asin, band):
        """市場 1 つの指標。売れ筋上位の商品から、市場の大きさと、上位の顔ぶれの強さを見る。

        推定月商 = 価格 × 月間販売数。月間販売数は「過去1か月で○点以上」の表示（なければランキングの動きからの推定）
        なので、下限の目安。季節商品のために、過去12か月でよく売れた3か月の平均（最盛期）でも見る。
        """
        lo, hi = band
        rows, seen = [], set()
        for a in target['asins']:
            r = rows_by_asin.get(a)
            if not r or r['parent'] in seen:                 # 色・サイズ違いは 1 件にまとめる
                continue
            seen.add(r['parent'])
            rows.append({k: v for k, v in r.items() if k != 'parent'})
        if target.get('by') == 'keyword':                    # キーワードで集めた市場は売れ筋順が無いので、月商の大きい順
            rows.sort(key=lambda r: -r['peakRev'])
        rows = rows[:MARKET_TOP]
        top = rows[:10]
        size, size_peak = sum(r['rev'] for r in top), sum(r['peakRev'] for r in top)
        by_brand = Counter()
        for r in top:
            by_brand[r['brand'] or '不明'] += r['peakRev']
        top_brand, top_rev = by_brand.most_common(1)[0] if by_brand else ('', 0)
        m = {
            'catId': str(target['catId']), 'name': target['name'], 'path': target.get('path') or [], 'kind': target['kind'],
            'by': target.get('by') or 'category', 'ownNames': target.get('ownNames') or [], 'n': len(rows),
            'size': size,                                                      # 上位10商品の推定月商の合計（いま）
            'sizePeak': size_peak,                                             # 同（最盛期）
            'seasonal': bool(size_peak) and size < size_peak * 0.5,            # いまは最盛期の半分以下 = 季節性がある
            'inBand': sum(1 for r in rows if lo <= r['peakRev'] <= hi),        # 狙う範囲の月商の商品数
            'over': sum(1 for r in rows if r['peakRev'] > hi),                 # 範囲を超える大型商品の数
            'big': sum(1 for r in top if r['big']),                            # 上位10のうち、Amazon本体が販売または出品者が多い商品
            'amazon': sum(1 for r in top if r['amazon']),
            'topBrand': top_brand, 'topShare': round(100.0 * top_rev / size_peak) if size_peak else None,
            'brands': len(by_brand),
            'estimated': sum(1 for r in top if r['est']),                      # 上位10のうち、販売数を推定で補った商品
            'unknown': sum(1 for r in top if not r['sold'] and not r['peak']), # 同、販売数が分からない商品
            'medReviews': _median([r['reviews'] for r in top if r['reviews'] is not None]),
            'medRating': _median([r['rating'] for r in top if r['rating'] is not None]),
            'medPrice': _median([r['price'] for r in top if r['price'] is not None]),
            'newWinners': sum(1 for r in rows if r['months'] is not None and r['months'] <= 12 and r['peakRev'] >= lo),
            'ownRev': sum(r['peakRev'] for r in rows if r['own']),
            'top': top,
        }
        m['fails'] = self.judge(m)
        return m

    def _family_keywords(self, parent):
        s = self.s_fam.get(parent) or {}
        return [k for k in (s.get('kw') or []) if k] or [k for k in ((self.candidates.get(parent) or {}).get('kw') or []) if k]

    def _known_titles(self):
        """これまでの取得で分かっている商品名（ASIN → 商品名）。市場の決め方の判定に使い、新しく取得はしない。"""
        out = {a: (v or {}).get('t') or '' for a, v in ((self.store.get('state/names') or {}).get('items') or {}).items()}
        for it in (self.store.get('views/comps') or {}).get('items') or []:
            out[it['asin']] = it.get('title') or ''
        for doc in self.candidates.values():
            for it in doc.get('items') or []:
                out[it['asin']] = it.get('title') or ''
        for f in self.families.values():
            for a in set(f.get('asins') or []) | set(f.get('variations') or []):
                out[a] = f.get('title') or ''
        return out

    def market_targets(self):
        """自社商品ごとに、どの範囲を市場として見るかを決める。

        基本は、いちばん細かいカテゴリの売れ筋。ただしカテゴリの上位が別の種類の商品ばかりのとき
        （小物が、別の種類の商品のカテゴリに入っている、など）は、競合候補として集めた
        「商品名にキーワードを含む商品」を市場とする。
        """
        titles = self._known_titles()
        cats = self.store.list('cats')
        by_cat, by_kw = {}, {}
        for parent, f in sorted(self.families.items()):
            c = f.get('cat') or {}
            cid = str(c.get('id') or '')
            doc = cats.get(cid) or {}
            days = sorted(doc.get('top') or {})
            ranking = doc['top'][days[-1]] if days else []
            kw = self._family_keywords(parent)
            known = [titles[a] for a in ranking[:10] if titles.get(a)]
            share = (sum(1 for t in known if any(k in t for k in kw)) / float(len(known))) if kw and len(known) >= 5 else None
            cand = [it['asin'] for g in ('rec', 'big') for it in ((self.candidates.get(parent) or {}).get('items') or []) if it.get('group') == g]
            if ranking and (share is None or share >= MARKET_COHERENCE or not cand):
                t = by_cat.setdefault(cid, {'catId': cid, 'name': doc.get('name') or c.get('name') or cid, 'kind': 'own', 'by': 'category',
                                            'path': [x.get('name') or '' for x in f.get('cats') or []], 'ownNames': [],
                                            'asins': ranking[:MARKET_TOP + 4]})
                t['ownNames'].append(f['name'])
            elif kw and cand:
                key = kw[0].strip().lower()
                t = by_kw.setdefault(key, {'catId': 'kw:' + key, 'name': kw[0].strip(), 'kind': 'own', 'by': 'keyword',
                                           'path': ['キーワードで集計'], 'ownNames': [], 'asins': []})
                t['ownNames'].append(f['name'])
                for a in [f['rep']] + cand:
                    if a not in t['asins'] and len(t['asins']) < MARKET_KEYWORD_POOL:
                        t['asins'].append(a)
        return list(by_cat.values()) + list(by_kw.values())

    def markets(self):
        """市場の指標を作る。自社が参入している市場と、比較用の市場（直近のリサーチ結果に多く出た市場）を数値化し、
        狙い目の基準に合うかを判定する。"""
        prm = self.research_params
        band = (prm['revMin'], prm['revMax'])
        own_all = set(self.own) | {a for f in self.families.values() for a in f['variations']}
        own_brands = {f['brand'].strip().lower() for f in self.families.values() if f.get('brand')}
        if not self.candidates:
            self.load_candidates()
        targets = self.market_targets()
        own_cats = {str((f.get('cat') or {}).get('id') or '') for f in self.families.values()}
        counts, info = Counter(), {}
        for it in (self.store.get('views/research') or {}).get('items') or []:
            c = it.get('cat') or {}
            if c.get('id') and str(c['id']) not in own_cats:
                counts[str(c['id'])] += 1
                info[str(c['id'])] = (c.get('name') or '', it.get('root') or '')
        for cid, _ in counts.most_common(MARKET_COMPARE):
            try:
                ranking = self.keepa.bestsellers(int(cid), label='市場（売れ筋）')
            except KeepaError as e:
                self.log('市場: 比較用の取得を中断（{}）'.format(e))
                break
            if ranking:
                name, root = info[cid]
                targets.append({'catId': cid, 'name': name, 'path': [x for x in (root, name) if x], 'kind': 'compare',
                                'asins': ranking[:MARKET_TOP + 4]})
        need = sorted({a for t in targets for a in t['asins']})
        rows = {}
        for i in range(0, len(need), 100):                   # 履歴つきの商品データは大きいので、100 件ごとに必要な値だけ残す
            try:
                prods = self.keepa.products(need[i:i + 100], history=True, days=MARKET_HISTORY_DAYS, rating=True, label='市場（商品）')
            except KeepaError as e:
                self.warnings.append('市場の評価を途中で止めました。')
                self.log('市場: 商品の取得を中断（{}）'.format(e))
                break
            for a, p in prods.items():
                rows[a] = self._market_row(p, own_all, own_brands)
        items = [m for m in (self.market_item(t, rows, band) for t in targets) if m['n']]
        items.sort(key=lambda m: (m['kind'] != 'own', len(m['fails']), -m['sizePeak']))
        n_badge = sum(1 for r in rows.values() if r['sold'] and not r['est'])
        n_est = sum(1 for r in rows.values() if r['est'])
        self.log('市場: {} 件を評価（自社が参入 {} うちキーワードで集計 {} / 比較 {}）。狙い目 {} 件'.format(
            len(items), sum(1 for m in items if m['kind'] == 'own'), sum(1 for m in items if m['by'] == 'keyword'),
            sum(1 for m in items if m['kind'] == 'compare'), sum(1 for m in items if not m['fails'])))
        self.log('市場: 商品 {} 件のうち、販売数の表示あり {} / ランキングから推定 {} / 不明 {}'.format(
            len(rows), n_badge, n_est, len(rows) - n_badge - n_est))
        return {'updatedAt': self._wall().isoformat(), 'band': list(band), 'rules': dict(MARKET_RULES), 'items': items}

    # ------------------------------------------------------------------ 通知
    def alerts(self, own_items, comp_items, cat_items):
        th, out = self.th, []
        flags = (self.store.get('state/flags') or {}).get('items') or {}
        new_flags = {}
        own_price = {i['parent']: i.get('price') for i in own_items}
        yen = lambda v: '{:,}円'.format(int(v))
        # 同じ競合を複数の自社商品で監視していても、通知は競合 1 件につき 1 つにまとめる
        by_comp = {}
        for c in comp_items:
            if not c.get('pending'):
                by_comp.setdefault(c['asin'], []).append(c)
        for asin, rows in by_comp.items():
            c = rows[0]
            name, acct = c['title'] or asin, c['acct']
            owns = []
            for r in rows:
                if r['ownName'] not in owns:
                    owns.append(r['ownName'])
            sub_own = '自社「{}」'.format(owns[0]) + (' ほか{}商品'.format(len(owns) - 1) if len(owns) > 1 else '')
            if c.get('price') and c.get('prev') and c['price'] < c['prev'] and not c.get('deal'):
                mines = [(own_price.get(r['parent']), r['ownName']) for r in rows if own_price.get(r['parent']) is not None]
                above = [(m, n) for m, n in mines if c['price'] < m]          # 競合より高い自社商品
                gap = ''
                if above:
                    m, n = max(above)
                    gap = '（自社「{}」{} より {} 安い）'.format(n, yen(m), yen(m - c['price']))
                out.append({'sev': 'crit' if above else 'warn', 'type': 'drop', 'tab': 'price', 'acct': acct,
                            'text': '{} が {} → {} に値下げ'.format(name, yen(c['prev']), yen(c['price'])), 'sub': sub_own + 'の競合' + gap})
            if c.get('couponNew') and c.get('coupon'):
                out.append({'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': acct,
                            'text': '{} が {} クーポンを開始'.format(name, c['coupon']), 'sub': sub_own + 'の競合'})
            if c.get('deal'):
                since = (flags.get(asin) or {}).get('dealSince') or self.iso
                new_flags[asin] = {'dealSince': since}
                if self._days_since(since) <= 1:
                    out.append({'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': acct,
                                'text': '{} が{}を開始'.format(name, c['deal']), 'sub': sub_own + 'の競合'})
            if c.get('stock') == 'out' and 0 < c.get('outDays', 0) <= th['outOfStockMaxDays']:
                out.append({'sev': 'good', 'type': 'stock', 'tab': 'stock', 'acct': acct,
                            'text': '{} が在庫切れ {}日目'.format(name, c['outDays']), 'sub': sub_own + 'の広告強化を検討できます'})
        for it in own_items:
            st, label, acct = it['status'], '「{}」'.format(it['name']), it['acct']
            cmp_text = '{}日前との比較'.format(it.get('cmpDays') or th['compareDays'])
            if st['label'] == '評価低下':
                out.append({'sev': 'crit', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}の評価が {:.1f} → {:.1f} に低下'.format(label, it['rating30'], it['rating']), 'sub': cmp_text})
            elif st['label'] == '販売数減少':
                now_text = '{:,}点以上'.format(it['sold']) if it.get('sold') else '表示なし（50点未満）'
                out.append({'sev': 'serious', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}の月間販売が {:,}点以上 → {} に減少'.format(label, it['sold30'], now_text),
                            'sub': cmp_text + '（Amazon の「過去1か月で○点以上購入」の表示）'})
            if it.get('changedAt') and self._days_since(it['changedAt']) <= th['pageChangeDays']:
                out.append({'sev': 'warn', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}の{}が変更されました'.format(label, it.get('changeWhat') or '商品ページ'),
                            'sub': '{} に検知。自社で変更していない場合は確認が必要です'.format(it['changedAt'])})
            if it.get('oos'):
                out.append({'sev': 'warn', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}に、在庫があるのに出品が表示されていない色・サイズが {}件あります'.format(label, it['oos']), 'sub': '出品停止やカート未取得の可能性があります'})
        for g in cat_items:
            for e in g['top']:
                if e['kind'] == 'new':
                    out.append({'sev': 'warn', 'type': 'entrant', 'tab': 'category', 'acct': (g['accts'] or [None])[0],
                                'text': '「{}」で {} が {}位に新規参入'.format(g['name'], e['title'], e['r']), 'sub': e['brand']})
        unset = [p for p in self.families if not self.effective_competitors(p)]
        if unset:
            out.append({'sev': 'warn', 'type': 'setup', 'tab': 'setup', 'acct': None,
                        'text': '競合が未設定の自社商品が {}件あります'.format(len(unset)), 'sub': '候補から競合を選ぶと監視が始まります'})
        if self.new_own:
            out.append({'sev': 'info', 'type': 'setup', 'tab': 'setup', 'acct': None,
                        'text': '新しい自社商品が {}件 追加されました'.format(len(self.new_own)), 'sub': 'ダッシュボードの在庫データから自動で取り込みました'})
        self.store.set('state/flags', {'updatedAt': self.now.isoformat(), 'items': new_flags})
        out.sort(key=lambda a: SEV_ORDER[a['sev']])
        return out

    # ------------------------------------------------------------------ 画面用データ
    def setup_view(self):
        items, comp_info = [], {(c['parent'], c['asin']): c for c in self.comp_items}
        for parent, fam in self.families.items():
            eff = self.effective_competitors(parent)
            s = self.s_fam.get(parent) or {}
            cand = self.candidates.get(parent)
            comps = []
            for asin, manual, auto in eff:
                c = comp_info.get((parent, asin)) or {}
                comps.append({'asin': asin, 'title': c.get('title') or '', 'brand': c.get('brand') or '', 'manual': manual, 'auto': auto,
                              'pending': bool(c.get('pending')) or not c})
            items.append({'parent': parent, 'acct': fam['account'], 'name': fam['name'], 'title': fam['title'], 'rep': fam['rep'],
                          'nvar': len(fam['asins']), 'isNew': self._days_since(fam.get('firstSeen')) <= 7,
                          'source': 'user' if s.get('competitors') else ('auto' if eff else 'none'),
                          'competitors': comps, 'hasCandidates': bool(cand), 'picks': len((cand or {}).get('picks') or []),
                          'kw': (cand or {}).get('kw') or [], 'terms': (cand or {}).get('terms') or []})
        items.sort(key=lambda x: (0 if x['source'] == 'none' else 1 if x['source'] == 'auto' else 2, x['acct'] or '', x['name']))
        return items

    def write_views(self, job, own_items=None, cat_items=None, sales=True):
        now = self._wall().isoformat()                    # 書き出した時刻
        if own_items is None:
            own_items = self.own_view()
            self.store.set('views/own', {'updatedAt': now, 'items': own_items})
        if cat_items is None:
            cat_items = self.cat_items
            self.store.set('views/cats', {'updatedAt': now, 'items': cat_items})
        self.store.set('views/comps', {'updatedAt': now, 'items': self.comp_items})
        if sales:
            self.store.set('views/sales', self.sales_view())
        own_asins = sorted({a for a, e in self.own.items() if not e.get('gone')} | {a for f in self.families.values() for a in f['variations']})
        self.store.set('views/setup', {'updatedAt': now, 'items': self.setup_view(), 'ownAsins': own_asins})
        alerts = self.alerts(own_items, self.comp_items, cat_items)
        usage = self.store.get('state/usage') or {'days': {}}
        usage['days'][self.iso] = (usage['days'].get(self.iso) or 0) + self.keepa.spent - getattr(self, '_usage_written', 0)
        self._usage_written = self.keepa.spent
        usage['days'] = dict(sorted(usage['days'].items())[-60:])
        self.store.set('state/usage', usage)
        self.store.set('views/overview', {
            'updatedAt': now, 'job': job, 'alerts': alerts, 'warnings': self.warnings, 'accounts': self.cfg.accounts,
            'counts': dict(Counter(a['type'] for a in alerts)),
            'monitor': {'families': len(self.families), 'asins': sum(len(f['asins']) for f in self.families.values()),
                        'competitors': len({c['asin'] for c in self.comp_items}),
                        'unset': sum(1 for p in self.families if not self.effective_competitors(p))},
            'tokens': {'spent': self.keepa.spent, 'today': usage['days'][self.iso], 'left': self.keepa.tokens_left,
                       'rate': self.keepa.refill_rate, 'byLabel': self.keepa.by_label, 'days': usage['days']},
        })
        self.log('画面用データを書き出しました（通知 {} 件 / 読み取り {} 回 / 書き込み {} 回）'.format(len(alerts), self.store.reads, self.store.writes))

    # ------------------------------------------------------------------ ジョブ
    def job_daily(self):
        """1日1回。自社商品の取り込みから全部を更新する。"""
        self.load_settings()
        self.sync_own()
        self.own_catalog()
        self.load_candidates()
        self.build_picks()
        self.competitors(rating=True)
        self.categories()
        self.write_views('daily')                         # ここまでで画面は最新になる
        if self.build_candidates(self.cfg.candidates_per_run):   # 候補作りは時間がかかるので後回し
            self.competitors(rating=True)
            self.write_views('daily')
        if self.today.weekday() == 0 or not self.store.get('views/research'):
            self.store.set('views/research', self.research())
            self.store.set('views/markets', self.markets())      # 週 1 回、リサーチのあとに市場も評価し直す
            self.write_views('daily')

    def job_prices(self):
        """1日数回。競合の価格・クーポン・セール・在庫だけを取り直す。"""
        self.load_settings()
        self.load_state()
        self.load_candidates()
        previous = (self.store.get('views/comps') or {}).get('items') or []
        self.competitors(days=90, rating=False, previous=previous)
        own_items = (self.store.get('views/own') or {}).get('items') or []
        cat_items = (self.store.get('views/cats') or {}).get('items') or []
        self.write_views('prices', own_items=own_items, cat_items=cat_items, sales=False)

    def job_auto(self):
        """予約実行から呼ぶ。いまの時刻と、今日すでに取得した内容を見て、必要なジョブだけを実行する。

        GitHub の予約実行は時刻が保証されず、遅れたり 1 回分が飛んだりする。そこで各回の時刻のあとに
        何度か起動させ、済んでいなければ実行し、済んでいれば何もせずに終える。
        済んだかどうかは、画面用データの更新時刻で判断する（手動で実行した分も数に入る）。
        """
        own_at = _parse_time((self.store.get('views/own') or {}).get('updatedAt'))          # 朝の取得だけが更新する
        comps_at = _parse_time((self.store.get('views/comps') or {}).get('updatedAt'))      # 競合を取得するたびに更新する
        start = DAILY_FROM[0] * 60 + DAILY_FROM[1]
        minute = self.now.hour * 60 + self.now.minute
        # 1 日の区切りは朝の取得の時刻。それより前に届いた起動は、前日の回の続きとして扱う
        day = self.today if minute >= start else self.today - timedelta(days=1)
        midnight = self.now.replace(hour=0, minute=0, second=0, microsecond=0) - (self.now.date() - day)
        if minute >= start and not (own_at is not None and own_at.date() == self.today):
            st = self.store.get('state/schedule') or {}
            if st.get('date') != self.iso:
                st = {'date': self.iso, 'tries': 0}
            if st['tries'] < MAX_DAILY_TRIES:
                st['tries'] += 1
                self.store.set('state/schedule', st)             # 途中で失敗しても、試した回数は残す
                self.log('予約実行: 朝の取得を実行します（今日 {} 回目）'.format(st['tries']))
                self.job_daily()
                return 'daily'
            self.log('予約実行: 朝の取得は今日 {} 回失敗しています。手動で確認してください'.format(st['tries']))
        due, later = [], []
        for h, m in PRICE_SLOTS:
            slot = midnight + timedelta(hours=h, minutes=m)
            if self.now < slot:
                later.append('{}時'.format(h))
            elif comps_at is None or comps_at < slot:
                due.append('{}時'.format(h))
        if due:
            self.log('予約実行: 競合の価格を取得します（{} の回）'.format('、'.join(due)))
            self.job_prices()
            return 'prices'
        self.log('予約実行: いま実行するものはありません（取得済み。次は {}）'.format(
            later[0] + 'の回' if later else '朝の取得'))
        return 'none'

    def _wall(self):
        """いまの時刻（開始時刻 + 経過時間）。"""
        return self.now + timedelta(seconds=int(time.monotonic() - self._t0))

    def job_candidates(self):
        """競合候補だけをまとめて作る（初回や、キーワードを直したあとに使う）。"""
        self.load_settings()
        self.load_state()
        self.load_candidates()
        if not self.families:
            raise RuntimeError('自社カタログがまだありません。先に daily を実行してください')
        self.own_products = {}
        built = self.build_candidates(0) + self.build_picks()
        previous = (self.store.get('views/comps') or {}).get('items') or []
        self.competitors(rating=True, previous=previous)
        own_items = (self.store.get('views/own') or {}).get('items') or []
        cat_items = (self.store.get('views/cats') or {}).get('items') or []
        self.write_views('candidates', own_items=own_items, cat_items=cat_items, sales=False)
        return built

    def job_research(self):
        """新商品リサーチと、市場の評価を実行する。"""
        self.load_settings()
        self.load_state()
        self.store.set('views/research', self.research())
        self.store.set('views/markets', self.markets())

    def job_markets(self):
        """市場の評価だけを実行する。"""
        self.load_settings()
        self.load_state()
        self.store.set('views/markets', self.markets())
