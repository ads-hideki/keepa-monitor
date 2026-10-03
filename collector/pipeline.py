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
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import dashboard, parse
from .config import DEFAULT_RESEARCH, DEFAULT_THRESHOLDS
from .keepa import KeepaError
from .parse import CSV_NEW, CSV_RATING, CSV_REVIEWS, CSV_SALES, JST

SEV_ORDER = {'crit': 0, 'serious': 1, 'warn': 2, 'good': 3, 'info': 4}
HISTORY_DAYS = 730      # 月別販売数を24か月分表示するため、履歴は2年分を取る（トークンは変わらない）


def _mean(values):
    vals = [v for v in values if isinstance(v, (int, float)) and v > 0]
    return round(sum(vals) / len(vals)) if vals else None


class Run:
    def __init__(self, store, keepa, cfg, now=None, log=print, dash_fetch=None):
        self.store, self.keepa, self.cfg, self.log = store, keepa, cfg, log
        self.now = now or datetime.now(JST)
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
        self.store.set('state/families', {'updatedAt': self.now.isoformat(), 'items': fams})
        self.families = fams
        self.log('自社カタログ: {} ASIN を取得、{} 商品にまとめました'.format(len(prods), len(fams)))

    def own_status(self, it):
        th = self.th
        if it.get('rating') is not None and it.get('rating7') is not None and it['rating7'] - it['rating'] >= th['ratingDrop'] - 1e-9:
            return {'sev': 'crit', 'label': '評価低下'}
        # 順位は日々大きく動くので、直近3日の平均と1週間前の3日の平均で比べる
        if it.get('rankNow3') and it.get('rankWeek3') and it['rankNow3'] >= it['rankWeek3'] * (1 + th['rankWorsePct'] / 100.0):
            return {'sev': 'serious', 'label': 'ランキング急落'}
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
            rating7 = parse.value_days_ago(rating_pts, 7, self.today)
            rank_hist = parse.daily(rank_pts, 30, self.today)
            prices = [v for v in (parse.current(m, CSV_NEW) for m in members) if v is not None]
            oos = [m['asin'] for m in members if parse.current(m, CSV_NEW) is None and (self.own.get(m['asin']) or {}).get('qty', 0) > 0]
            it = {
                'parent': parent, 'acct': fam['account'], 'name': fam['name'], 'title': fam['title'], 'rep': fam['rep'],
                'image': b['image'], 'nvar': len(fam['asins']), 'cat': (fam.get('cat') or {}).get('name'),
                'price': b['price'], 'priceMin': min(prices) if prices else None, 'priceMax': max(prices) if prices else None,
                'priceHist': parse.compress(parse.daily(parse.changes(rep, CSV_NEW), 90, self.today)),
                'rank': b['rank'], 'rank7': parse.value_days_ago(rank_pts, 7, self.today),
                'rankHist': rank_hist, 'rankNow3': _mean(rank_hist[-3:]), 'rankWeek3': _mean(rank_hist[-10:-7]),
                'rating': b['rating'], 'rating7': (rating7 / 10.0) if rating7 is not None and rating7 >= 0 else None,
                'reviews': b['reviews'], 'reviews7': parse.value_days_ago(rev_pts, 7, self.today),
                'sold': b['sold'], 'coupon': b['coupon'], 'deal': b['deal'],
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
        if cand:
            return [(i['asin'], False, True) for i in cand.get('items') or [] if i.get('auto')]
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
        self.cat_items = items
        self.log('カテゴリ順位: {} カテゴリ'.format(len(items)))
        return items

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
            self.store.set('candidates/{}'.format(parent), doc)
            self.candidates[parent] = doc
            built += 1
        self.log('競合候補: {} 商品分を作成（対象 {}）'.format(built, len(todo)))
        return built

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
                          'group': d['group'], 'why': d['why'], 'auto': d['group'] == 'rec' and n < 2})
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
        prm = self.research_params
        roots = sorted({f['cats'][0]['id'] for f in self.families.values() if f.get('cats') and f['cats'][0].get('id')})
        view = {'updatedAt': self.now.isoformat(), 'params': prm, 'items': [], 'error': None}
        if not roots:
            view['error'] = '自社商品のカテゴリがまだ取得できていません'
            return view
        own_brands = {f['brand'].strip().lower() for f in self.families.values() if f.get('brand')}
        try:
            selection = {'rootCategory': roots, 'current_NEW_gte': prm['priceMin'], 'current_NEW_lte': prm['priceMax'],
                         'monthlySold_gte': prm['soldMin'], 'perPage': 100, 'page': 0, 'sort': [['current_SALES', 'asc']]}
            asins, total = self.keepa.finder(selection)
            prods = self.keepa.products(asins[:100], history=False, rating=True, label='リサーチ（商品）')
        except KeepaError as e:
            view['error'] = '取得に失敗しました: {}'.format(e)
            self.warnings.append('新商品リサーチの取得に失敗しました。')
            return view
        seen = set()
        for a in asins:
            p = prods.get(a)
            if not p:
                continue
            b = parse.brief(p)
            if b['parent'] in seen or b['brand'].strip().lower() in own_brands or b['brand'].strip().lower() in self.excluded_brands:
                continue
            if b['amazonSells'] or (b['offers'] is not None and b['offers'] > self.th['maxOffersForPb']):
                continue
            if (b['reviews'] or 0) > prm['reviewsMax'] or (b['rank'] or 10 ** 9) > prm['rankMax']:
                continue
            seen.add(b['parent'])
            b['listed'] = parse.to_date(p.get('listedSince'))
            b['title'] = b['title'][:80]
            view['items'].append(b)
            if len(view['items']) >= prm['limit']:
                break
        view['matched'] = total
        self.log('新商品リサーチ: {} 件'.format(len(view['items'])))
        return view

    # ------------------------------------------------------------------ 通知
    def alerts(self, own_items, comp_items, cat_items):
        th, out = self.th, []
        flags = (self.store.get('state/flags') or {}).get('items') or {}
        new_flags = {}
        own_price = {i['parent']: i.get('price') for i in own_items}
        yen = lambda v: '{:,}円'.format(int(v))
        for c in comp_items:
            if c.get('pending'):
                continue
            name, acct, mine = c['title'] or c['asin'], c['acct'], own_price.get(c['parent'])
            sub_own = '自社「{}」'.format(c['ownName'])
            if c.get('price') and c.get('prev') and c['price'] < c['prev'] and not c.get('deal'):
                cheaper = mine is not None and c['price'] < mine
                gap = '（自社 {} より {} 安い）'.format(yen(mine), yen(mine - c['price'])) if cheaper else ''
                out.append({'sev': 'crit' if cheaper else 'warn', 'type': 'drop', 'tab': 'price', 'acct': acct,
                            'text': '{} が {} → {} に値下げ'.format(name, yen(c['prev']), yen(c['price'])), 'sub': sub_own + 'の競合' + gap})
            if c.get('couponNew') and c.get('coupon'):
                out.append({'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': acct,
                            'text': '{} が {} クーポンを開始'.format(name, c['coupon']), 'sub': sub_own + 'の競合'})
            if c.get('deal'):
                since = (flags.get(c['asin']) or {}).get('dealSince') or self.iso
                new_flags[c['asin']] = {'dealSince': since}
                if self._days_since(since) <= 1:
                    out.append({'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': acct,
                                'text': '{} が{}を開始'.format(name, c['deal']), 'sub': sub_own + 'の競合'})
            if c.get('stock') == 'out' and 0 < c.get('outDays', 0) <= th['outOfStockMaxDays']:
                out.append({'sev': 'good', 'type': 'stock', 'tab': 'stock', 'acct': acct,
                            'text': '{} が在庫切れ {}日目'.format(name, c['outDays']), 'sub': sub_own + 'の広告強化を検討できます'})
        for it in own_items:
            st, label, acct = it['status'], '「{}」'.format(it['name']), it['acct']
            if st['label'] == '評価低下':
                out.append({'sev': 'crit', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}の評価が {:.1f} → {:.1f} に低下'.format(label, it['rating7'], it['rating']), 'sub': '7日前との比較'})
            elif st['label'] == 'ランキング急落':
                out.append({'sev': 'serious', 'type': 'catalog', 'tab': 'catalog', 'acct': acct,
                            'text': '{}のランキングが {:,}位 → {:,}位 に下落'.format(label, it['rankWeek3'], it['rankNow3']), 'sub': '直近3日の平均と、1週間前の3日の平均との比較'})
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
                          'competitors': comps, 'hasCandidates': bool(cand),
                          'kw': (cand or {}).get('kw') or [], 'terms': (cand or {}).get('terms') or []})
        items.sort(key=lambda x: (0 if x['source'] == 'none' else 1 if x['source'] == 'auto' else 2, x['acct'] or '', x['name']))
        return items

    def write_views(self, job, own_items=None, cat_items=None, sales=True):
        now = self.now.isoformat()
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
        self.competitors(rating=True)
        self.categories()
        self.write_views('daily')                         # ここまでで画面は最新になる
        if self.build_candidates(self.cfg.candidates_per_run):   # 候補作りは時間がかかるので後回し
            self.competitors(rating=True)
            self.write_views('daily')
        if self.today.weekday() == 0 or not self.store.get('views/research'):
            self.store.set('views/research', self.research())
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

    def job_candidates(self):
        """競合候補だけをまとめて作る（初回や、キーワードを直したあとに使う）。"""
        self.load_settings()
        self.load_state()
        self.load_candidates()
        if not self.families:
            raise RuntimeError('自社カタログがまだありません。先に daily を実行してください')
        self.own_products = {}
        built = self.build_candidates(0)
        previous = (self.store.get('views/comps') or {}).get('items') or []
        self.competitors(rating=True, previous=previous)
        own_items = (self.store.get('views/own') or {}).get('items') or []
        cat_items = (self.store.get('views/cats') or {}).get('items') or []
        self.write_views('candidates', own_items=own_items, cat_items=cat_items, sales=False)
        return built

    def job_research(self):
        self.load_settings()
        self.load_state()
        self.store.set('views/research', self.research())
