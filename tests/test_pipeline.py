# -*- coding: utf-8 -*-
"""全体を通しで動かすテスト。商品名や ASIN はすべて架空。"""
import re
from datetime import timedelta

from collector.keepa import Keepa
from collector.pipeline import Run
from collector.store import MemoryStore

from fakes import NOW, Cfg, FakeKeepaHttp, dashboard_fetch, km, product

TREE_A = ((1, 'ルート'), (11, 'クッション'))
TREE_B = ((2, 'ルート2'), (22, 'スプレー'))


def world(now=NOW):
    fam = ['B0OWN00001', 'B0OWN00002', 'B0OWN00003']
    p = {}
    # 自社: 3色展開の商品（月間の購入数の表示が 400 → 200 に減少）と、単品（評価が 4.3 → 4.1 に低下）
    for a in fam:
        p[a] = product(a, '自社ブランド 低反発 クッション 【説明】 椅子用 ' + a[-1], brand='自社ブランド', parent='B0PARENT01', variations=fam,
                       price=((400, 2800),), rank=((400, 1000), (3, 1600)), sold=((60, 400), (10, 200)), tree=TREE_A, now=now)
    p['B0OWN00004'] = product('B0OWN00004', '自社ブランド カビ取り スプレー 強力', brand='自社ブランド', price=((400, 1480),),
                              rating=((400, 43), (2, 41)), tree=TREE_B, coupon=[-5, 0], now=now)
    # カテゴリ A の商品
    p['B0CMP00001'] = product('B0CMP00001', '大手 低反発 クッション', brand='大手', amazon=2500, offers=12, tree=TREE_A, now=now)
    p['B0CMP00002'] = product('B0CMP00002', 'PB甲 低反発 クッション 椅子用', brand='PB甲', price=((400, 3000), (0.5, 2500)), tree=TREE_A, now=now)
    p['B0CMP00003'] = product('B0CMP00003', 'PB乙 クッション 椅子用', brand='PB乙', coupon=[-10, 0],
                              coupon_hist=[km(now - timedelta(days=30)), 0, 0, km(now - timedelta(hours=5)), -10, 0], tree=TREE_A, now=now)
    p['B0CMP00004'] = product('B0CMP00004', 'PB丙 クッション 椅子用 色違い', brand='PB乙', parent='B0CMPPAR03', tree=TREE_A, now=now)
    p['B0CMP00005'] = product('B0CMP00005', '収納ボックス', brand='別物', tree=TREE_A, now=now)
    for i in range(6, 46):
        a = 'B0CMP{:05d}'.format(i)
        p[a] = product(a, 'PB{} クッション 丸型'.format(i), brand='PB{}'.format(i), tree=TREE_A, now=now)
    p['B0CMP00003']['parentAsin'] = 'B0CMPPAR03'
    # カテゴリ B の商品（在庫切れ 3 日目、セール中）
    p['B0SPR00001'] = product('B0SPR00001', 'PB丁 カビ取り スプレー', brand='PB丁', price=((400, 1980), (2.2, -1)), tree=TREE_B, now=now)
    p['B0SPR00002'] = product('B0SPR00002', 'PB戊 カビ取り スプレー 泡', brand='PB戊', deals=[{'badge': 'タイムセール', 'dealType': 'LIMITED_TIME_DEAL'}], tree=TREE_B, now=now)
    for i in range(3, 20):
        a = 'B0SPR{:05d}'.format(i)
        p[a] = product(a, 'PB{} カビ取り 洗剤'.format(i), brand='SPB{}'.format(i), tree=TREE_B, now=now)
    best = {11: ['B0CMP00001', 'B0CMP00002', 'B0OWN00002', 'B0CMP00003', 'B0CMP00004', 'B0CMP00005'] + ['B0CMP{:05d}'.format(i) for i in range(6, 46)],
            22: ['B0SPR{:05d}'.format(i) for i in range(1, 5)] + ['B0OWN00004'] + ['B0SPR{:05d}'.format(i) for i in range(5, 20)]}
    searches = {'低反発 クッション': ['B0CMP00002', 'B0CMP00044'], 'カビ取り スプレー': ['B0SPR00002', 'B0SPR00001']}
    return p, best, searches


def dash_docs():
    def item(asin, total=10, name='商品', sku='SKU'):
        return {'asin': asin, 'sku': sku, 'name': name, 'qty': total, 'total': total, 'inbound': 0}
    return {
        'inventory/fba_shop1': {'updated_at': 'x', 'items': {
            'X1': item('B0OWN00001'), 'X2': item('B0OWN00002', 50), 'X3': item('B0OWN00003'),
            'X9': item('B0NOSTOCK1', 0), 'XD': item('B0DUMMY001', 0, name='納品不備商品 計上専用ASIN'),
            'XS': item('B0OWN00004', 0)}},
        'inventory/fba_shop2': {'updated_at': 'x', 'items': {'Y1': item('B0OWN00004', 30)}},
    }


def make(store=None, now=NOW, http=None, cfg=None):
    products, best, searches = world(now)
    http = http or FakeKeepaHttp(products, best, searches)
    logs, slept = [], []

    def sleep(sec):
        slept.append(sec)
        http.refill(sec)

    keepa = Keepa('TESTKEY', http=http, sleep=sleep, clock=lambda: 0, log=logs.append)
    store = store or MemoryStore()
    run = Run(store, keepa, cfg or Cfg(), now=now, log=logs.append, dash_fetch=dashboard_fetch(dash_docs()))
    return run, store, http, logs, slept


def test_daily_builds_everything():
    run, store, http, logs, _ = make()
    store.set('settings/families', {'items': {'B0OWN00004': {
        'competitors': {'B0SPR00001': {'on': True}, 'B0SPR00002': {'on': True}, 'B0SPR00009': {'on': False},
                        'B0MANUAL01': {'on': True, 'manual': True}},
        'kw': ['カビ取り'], 'terms': ['カビ取り スプレー']}}})
    run.job_daily()

    own = store.get('state/own')['items']
    assert 'B0DUMMY001' not in own                      # 商品でない ASIN は除外
    assert own['B0OWN00004']['account'] == 'shop2'      # 在庫の多いアカウントに寄せる
    assert own['B0NOSTOCK1']['active'] is False         # 在庫のない商品は監視しない

    fams = store.get('state/families')['items']
    assert set(fams) == {'B0PARENT01', 'B0OWN00004'}
    assert fams['B0PARENT01']['asins'] == ['B0OWN00001', 'B0OWN00002', 'B0OWN00003']
    assert fams['B0PARENT01']['rep'] == 'B0OWN00002'    # 在庫の多い色が代表

    cand = store.get('candidates/B0PARENT01')
    groups = {i['asin']: i['group'] for i in cand['items']}
    assert groups['B0CMP00001'] == 'big' and groups['B0CMP00005'] == 'other' and groups['B0CMP00002'] == 'rec'
    assert 'B0CMP00004' not in groups                   # 同じ親の色違いは 1 件にまとめる
    assert [i['asin'] for i in cand['items'] if i['auto']] == ['B0CMP00002', 'B0CMP00003']
    assert all(a not in groups for a in ('B0OWN00001', 'B0OWN00002'))

    comps = {(c['parent'], c['asin']): c for c in store.get('views/comps')['items']}
    drop = comps[('B0PARENT01', 'B0CMP00002')]
    assert drop['price'] == 2500 and drop['prev'] == 3000 and drop['auto'] is True
    assert comps[('B0OWN00004', 'B0SPR00001')]['stock'] == 'out' and comps[('B0OWN00004', 'B0SPR00001')]['outDays'] == 3
    assert comps[('B0OWN00004', 'B0MANUAL01')]['pending'] is True
    assert ('B0OWN00004', 'B0SPR00009') not in comps    # オフにした競合は監視しない

    ov = store.get('views/overview')
    texts = ' / '.join(a['text'] for a in ov['alerts'])
    assert '値下げ' in texts and 'クーポンを開始' in texts and '在庫切れ 3日目' in texts
    assert 'タイムセール' not in texts                   # 監視を始めた日に、すでに始まっていたセールは「開始」として通知しない
    assert '評価が 4.3 → 4.1' in texts and '月間販売が 400点以上 → 200点以上 に減少' in texts
    assert 'ランキング' not in texts                     # 順位の上下では通知しない（日々の動きが大きいため）
    own_items = {o['parent']: o for o in store.get('views/own')['items']}
    assert own_items['B0PARENT01']['status']['label'] == '販売数減少' and own_items['B0PARENT01']['sold30'] == 400
    assert own_items['B0OWN00004']['rating30'] == 4.3 and own_items['B0OWN00004']['cmpDays'] == 30
    assert [a['sev'] for a in ov['alerts']] == sorted([a['sev'] for a in ov['alerts']], key=['crit', 'serious', 'warn', 'good', 'info'].index)
    assert ov['monitor'] == {'families': 2, 'asins': 4, 'competitors': 5, 'unset': 0}
    assert ov['tokens']['spent'] == run.keepa.spent > 0

    cats = {c['catId']: c for c in store.get('views/cats')['items']}
    assert [t['kind'] for t in cats[11]['top'][:4]] == ['other', 'comp', 'own', 'comp'] or cats[11]['top'][2]['kind'] == 'own'
    own_track = [t for t in cats[22]['tracks'] if t['kind'] == 'own'][0]
    assert own_track['hist'][-1] == 5

    sales = store.get('views/sales')
    assert len(sales['months']) == 24 and sales['own']['B0PARENT01'][-1] == 200
    assert store.get('views/research') is not None
    # 公開リポジトリのログに、商品名・ASIN・キーを出さない
    joined = '\n'.join(str(x) for x in logs)
    assert not re.search(r'B0[A-Z0-9]{8}', joined) and 'TESTKEY' not in joined and 'クッション' not in joined


def test_second_day_detects_page_change_and_new_entrant():
    run, store, _, _, _ = make()
    run.job_daily()
    doc = store.get('cats/11')
    doc['top'] = {(NOW - timedelta(days=d)).strftime('%Y-%m-%d'): doc['top'][NOW.strftime('%Y-%m-%d')] for d in range(1, 10)}
    store.set('cats/11', doc)

    day2 = NOW + timedelta(days=1)
    products, best, searches = world(day2)
    products['B0OWN00004']['title'] = '自社ブランド カビ取り スプレー 改良版'
    products['B0NEWCOMER'] = product('B0NEWCOMER', '新参 クッション', brand='新参', tree=TREE_A, now=day2)
    best[11] = ['B0NEWCOMER'] + best[11]
    run2, _, _, _, _ = make(store=store, now=day2, http=FakeKeepaHttp(products, best, searches))
    run2.job_daily()
    ov = store.get('views/overview')
    texts = ' / '.join(a['text'] for a in ov['alerts'])
    assert '商品タイトルが変更されました' in texts
    assert '新規参入' in texts and '新参 クッション' in texts
    top = store.get('views/cats')['items']
    row = [t for c in top if c['catId'] == 11 for t in c['top'] if t['asin'] == 'B0CMP00001'][0]
    assert row['r'] == 2 and row['p7'] == 1


def test_prices_job_keeps_rating_and_updates_price():
    run, store, _, _, _ = make()
    run.job_daily()
    later = NOW + timedelta(hours=6)
    products, best, searches = world(later)
    products['B0CMP00003']['stats']['current'][1] = 2700
    products['B0CMP00003']['csv'][1] += [km(later - timedelta(hours=1)), 2700]
    for p in products.values():                       # rating=0 では評価が返らない想定
        p['stats']['current'][16] = -1
    http = FakeKeepaHttp(products, best, searches)
    run2, _, _, _, _ = make(store=store, now=later, http=http)
    run2.job_prices()
    comps = {(c['parent'], c['asin']): c for c in store.get('views/comps')['items']}
    c = comps[('B0PARENT01', 'B0CMP00003')]
    assert c['price'] == 2700 and c['rating'] == 4.3
    assert all(path != 'bestsellers' for path, _ in http.requests)      # 価格だけのジョブはランキングを取らない
    assert store.get('views/overview')['job'] == 'prices'
    assert len(store.get('views/own')['items']) == 2                     # 自社の表示は前回のまま残る


def test_waits_for_tokens_instead_of_failing():
    products, best, searches = world()
    http = FakeKeepaHttp(products, best, searches, tokens=20)
    run, store, _, logs, slept = make(http=http)
    run.job_daily()
    assert slept, 'トークン不足のときは回復を待つ'
    assert store.get('views/overview')['monitor']['families'] == 2


def test_dashboard_failure_uses_previous_list():
    run, store, _, _, _ = make()
    run.job_daily()

    def broken(project_id, doc_path, api_key=None):
        from collector.dashboard import DashboardError
        raise DashboardError('ダッシュボードの在庫データを読めませんでした（HTTP 403）')
    run2, _, _, _, _ = make(store=store, now=NOW + timedelta(days=1))
    run2.dash_fetch = broken
    run2.job_daily()
    ov = store.get('views/overview')
    assert ov['monitor']['families'] == 2 and any('前回の一覧' in w for w in ov['warnings'])


def test_candidate_limit_and_regenerate():
    cfg = Cfg()
    cfg.candidates_per_run = 1
    run, store, _, _, _ = make(cfg=cfg)
    run.job_daily()
    assert len(store.list('candidates')) == 1
    cfg.candidates_per_run = 0
    run2, _, _, _, _ = make(store=store, now=NOW + timedelta(hours=1), cfg=cfg)
    assert run2.job_candidates() == 1
    assert len(store.list('candidates')) == 2
    # キーワードを直して作り直しを指示すると、その商品だけ作り直す
    later = NOW + timedelta(hours=2)
    store.set('settings/families', {'items': {'B0PARENT01': {'kw': ['丸型'], 'terms': ['低反発 クッション'], 'regenAt': later.isoformat()}}})
    run3, _, _, _, _ = make(store=store, now=later + timedelta(minutes=5), cfg=cfg)
    assert run3.job_candidates() == 1
    assert store.get('candidates/B0PARENT01')['kw'] == ['丸型']


def test_auto_runs_each_slot_once_and_skips_when_done():
    at = lambda h, m: NOW.replace(hour=h, minute=m)
    store = MemoryStore()
    run, _, _, _, _ = make(store=store, now=at(19, 20) - timedelta(days=1))
    run.job_daily()                                                  # 前日の夜までに取得済み
    run, _, http, _, _ = make(store=store, now=at(1, 30))
    assert run.job_auto() == 'none' and not http.requests            # 2時より前は、朝の取得を始めない
    run, _, _, _, _ = make(store=store, now=at(2, 7))
    assert run.job_auto() == 'daily' and store.get('views/overview')['job'] == 'daily'
    run, _, http, logs, _ = make(store=store, now=at(2, 37))
    assert run.job_auto() == 'none' and not http.requests            # 予備の起動は Keepa を呼ばずに終わる
    assert any('取得済み' in line for line in logs)
    run, _, _, _, _ = make(store=store, now=at(10, 7))
    assert run.job_auto() == 'prices' and store.get('views/overview')['job'] == 'prices'
    run, _, http, _, _ = make(store=store, now=at(10, 37))
    assert run.job_auto() == 'none' and not http.requests
    run, _, _, logs, _ = make(store=store, now=at(19, 37))            # 14時の回が飛んでも、19時の起動でまとめて済ませる
    assert run.job_auto() == 'prices' and any('14時、19時' in line for line in logs)
    run, _, http, _, _ = make(store=store, now=at(20, 7))
    assert run.job_auto() == 'none' and not http.requests
    run, _, _, _, _ = make(store=store, now=at(2, 7) + timedelta(days=1))
    assert run.job_auto() == 'daily'                                 # 翌日はまた朝の取得から


def test_auto_counts_manual_runs_and_gives_up_after_failures():
    at = lambda h, m: NOW.replace(hour=h, minute=m)
    store = MemoryStore()
    run, _, _, _, _ = make(store=store, now=at(10, 7))                # 朝の起動が全部飛んだ日は、10時の起動で朝の取得を行う
    assert run.job_auto() == 'daily'
    run, _, http, _, _ = make(store=store, now=at(10, 37))
    assert run.job_auto() == 'none' and not http.requests            # 10時の回も済んだ扱い

    store = MemoryStore()
    run, _, _, _, _ = make(store=store, now=at(7, 50))
    run.job_daily()                                                  # 手動で実行した分も数に入る
    run, _, http, _, _ = make(store=store, now=at(8, 7))
    assert run.job_auto() == 'none' and not http.requests

    store = MemoryStore()
    for n in range(3):                                               # 朝の取得が 3 回続けて失敗
        run, _, _, _, _ = make(store=store, now=at(2, 7 + n))
        run.job_daily = lambda: (_ for _ in ()).throw(RuntimeError('x'))
        try:
            run.job_auto()
        except RuntimeError:
            pass
    assert store.get('state/schedule')['tries'] == 3
    run, _, http, logs, _ = make(store=store, now=at(4, 7))
    assert run.job_auto() == 'none' and not http.requests            # 4 回目は試さない
    assert any('失敗' in line for line in logs)


def test_auto_trigger_arriving_after_midnight_covers_previous_evening():
    at = lambda h, m: NOW.replace(hour=h, minute=m)
    store = MemoryStore()
    run, _, _, _, _ = make(store=store, now=at(15, 44) - timedelta(days=1))
    run.job_daily()                                                  # 前日は 15:44 が最後の取得
    run, _, _, logs, _ = make(store=store, now=at(0, 16))             # 19時の起動が日付をまたいで届いた
    assert run.job_auto() == 'prices' and any('19時' in line for line in logs)
    run, _, http, logs, _ = make(store=store, now=at(0, 47))
    assert run.job_auto() == 'none' and not http.requests
    assert any('次は 朝の取得' in line for line in logs)
    run, _, _, _, _ = make(store=store, now=at(2, 7))
    assert run.job_auto() == 'daily'


def test_one_alert_per_competitor_even_when_watched_by_several_products():
    run, store, _, _, _ = make()
    run.job_daily()
    comps = store.get('views/comps')['items']
    doubled = comps + [dict(c, parent='B0OTHERPAR', ownName='別の自社商品') for c in comps]
    alerts = run.alerts(store.get('views/own')['items'], doubled, store.get('views/cats')['items'])
    base = run.alerts(store.get('views/own')['items'], comps, store.get('views/cats')['items'])
    comp_types = ('drop', 'promo', 'stock')
    assert sum(a['type'] in comp_types for a in alerts) == sum(a['type'] in comp_types for a in base)
    assert any('ほか1商品' in a['sub'] for a in alerts if a['type'] in comp_types)


def test_research_searches_all_categories_and_drops_excluded_roots():
    products, best, searches = world()
    products['B0RSCBOOK1'] = product('B0RSCBOOK1', '架空の本', brand='出版社', tree=((9, '本'), (91, '実用書')))
    products['B0RSCPET01'] = product('B0RSCPET01', '猫用 食器', brand='PBペット', tree=((8, 'ペット用品'), (81, '食器')))
    products['B0RSCGAME1'] = product('B0RSCGAME1', 'ゲームソフト', brand='会社', tree=((7, 'TVゲーム'), (71, 'ソフト')))
    http = FakeKeepaHttp(products, best, searches, finder=['B0RSCBOOK1', 'B0OWN00004', 'B0RSCPET01', 'B0RSCGAME1', 'B0CMP00006'])
    run, store, _, _, _ = make(http=http)
    run.job_daily()
    view = store.get('views/research')
    assert [i['asin'] for i in view['items']] == ['B0RSCPET01', 'B0CMP00006']        # 本とゲームは外れ、自社商品も出ない
    assert view['items'][0]['root'] == 'ペット用品' and view['sort'] == 'sold'
    assert {'本', 'ペット用品', 'TVゲーム'} <= set(view['roots'])                      # 画面の選択肢に使う
    body = [b for path, b in http.bodies if path == 'query'][0]
    assert 'rootCategory' not in body and 'categories_include' not in body          # カテゴリでは絞らない

    store.set('settings/research', {'excludeRoots': ['ペット用品']})                 # 画面で外す対象を変えた場合
    run2, _, _, _, _ = make(store=store, http=FakeKeepaHttp(products, best, searches, finder=list(http.finder)))
    run2.job_research()
    assert [i['asin'] for i in store.get('views/research')['items']] == ['B0RSCBOOK1', 'B0RSCGAME1', 'B0CMP00006']


def test_markets_measures_own_and_comparison_markets():
    products, best, searches = world()
    # 比較用の市場: 大型商品ばかりで、Amazon 本体も売っている
    big = ['B0BIG{:05d}'.format(i) for i in range(1, 13)]
    for i, a in enumerate(big):
        products[a] = product(a, '大手 プロテイン {}'.format(i), brand='大手A' if i < 6 else '大手B', price=((400, 5000),),
                              reviews=((400, 4000 + i),), sold=((20, 10000),), amazon=4800 if i % 2 == 0 else None,
                              offers=8, tree=((3, 'ドラッグストア'), (33, 'プロテイン')))
    best[33] = big
    http = FakeKeepaHttp(products, best, searches, finder=big[:3])
    run, store, _, _, _ = make(http=http)
    run.job_daily()                                       # リサーチ結果（比較用の市場のもと）と売れ筋の記録を作る
    store.set('views/research', {'items': [{'asin': big[0], 'cat': {'id': 33, 'name': 'プロテイン'}, 'root': 'ドラッグストア'}]})
    run2, _, http2, _, _ = make(store=store, http=FakeKeepaHttp(products, best, searches))
    run2.job_markets()
    view = store.get('views/markets')
    assert view['band'] == [300000, 5000000]
    by = {m['name']: m for m in view['items']}
    own, cmp_ = by['クッション'], by['プロテイン']
    assert own['kind'] == 'own' and own['ownNames'] and own['ownParents'] == ['B0PARENT01'] and cmp_['kind'] == 'compare'
    assert [path for path, q in http2.requests if path == 'bestsellers'] == ['bestsellers']      # 自社の市場は売れ筋を取り直さない
    # 自社の市場: 価格 3,000円前後 × 月 400点 = 月商 120万円前後の商品が並ぶ。大手は 1 件だけ
    assert own['inBand'] >= 5 and own['over'] == 0 and own['big'] == 1 and own['ownRev'] > 0
    assert any(r['own'] for r in own['top'])
    # 比較用の市場: 月商 5,000万円の商品ばかりで、狙う範囲の商品はない
    assert cmp_['inBand'] == 0 and cmp_['over'] == 12 and cmp_['big'] == 10 and cmp_['amazon'] == 5
    assert cmp_['size'] == 10 * 5000 * 10000 and cmp_['topBrand'] == '大手A' and cmp_['topShare'] == 60
    assert cmp_['medReviews'] > 1000 > own['medReviews']
    assert view['items'][0]['kind'] == 'own' and view['items'][-1]['kind'] == 'compare'


def test_markets_use_keywords_when_the_category_is_about_something_else():
    products, best, searches = world()
    # カテゴリ B（スプレー）の上位を、自社商品とは別の種類の商品に入れ替える。キーワード「カビ取り」を含むのは自社と検索結果だけ
    others = ['B0OTH{:05d}'.format(i) for i in range(1, 25)]
    for i, a in enumerate(others):
        products[a] = product(a, '別ブランド{} スマホ ケース'.format(i), brand='OTH{}'.format(i), tree=TREE_B)
    best[22] = others[:4] + ['B0OWN00004'] + others[4:]
    # 検索で見つかる同じ種類の商品。1 件は販売数の表示がなく、ランキングの動きから推定する
    products['B0SPR00001'] = product('B0SPR00001', 'PB丁 カビ取り スプレー', brand='PB丁', price=((400, 2000),), sold=None, drops=120, tree=TREE_B)
    products['B0SPR00002'] = product('B0SPR00002', 'PB戊 カビ取り スプレー 泡', brand='PB戊', price=((400, 1000),),
                                     sold=((150, 3000), (120, 3000), (90, 3000), (30, 200)), tree=TREE_B)
    searches['カビ取り'] = ['B0SPR00002', 'B0SPR00001', 'B0SPR00003']
    run, store, _, _, _ = make(http=FakeKeepaHttp(products, best, searches))
    run.job_daily()
    assert store.get('candidates/B0OWN00004')['kw']                              # キーワードは候補作りで決まる
    run2, _, http2, logs, _ = make(store=store, http=FakeKeepaHttp(products, best, searches))
    run2.job_markets()
    view = store.get('views/markets')
    by = {m['catId']: m for m in view['items']}
    assert '22' not in by                                                        # 別の種類ばかりのカテゴリは市場にしない
    kw = [m for m in view['items'] if m['by'] == 'keyword'][0]
    assert kw['kind'] == 'own' and kw['path'] == ['キーワードで集計'] and kw['ownNames']
    assert all('カビ取り' in r['title'] for r in kw['top']) and any(r['own'] for r in kw['top'])
    rows = {r['asin']: r for r in kw['top']}
    assert rows['B0SPR00001']['sold'] == 120 and rows['B0SPR00001']['est'] and rows['B0SPR00001']['rev'] == 240000
    season = rows['B0SPR00002']                                                  # いまは 200 点、最盛期は 3000 点
    assert season['sold'] == 200 and season['peak'] == 3000 and season['peakRev'] == 3000000 and season['rev'] == 200000
    assert kw['top'][0]['asin'] == 'B0SPR00002'                                  # 最盛期の月商が大きい順
    assert kw['sizePeak'] > kw['size'] and kw['seasonal'] and kw['estimated'] == 1
    assert by['11']['by'] == 'category'                                          # 同じ種類が並ぶカテゴリはそのまま使う
    hist = [q for path, q in http2.requests if path == 'product']
    assert hist and all(q['history'] == '1' and q['days'] == '400' for q in hist)
    assert any('ランキングから推定 1' in line for line in logs)


def test_markets_use_the_proposals_when_the_category_is_about_something_else():
    products, best, searches = world()
    others = ['B0OTH{:05d}'.format(i) for i in range(1, 25)]
    for i, a in enumerate(others):
        products[a] = product(a, '別ブランド{} スマホ ケース'.format(i), brand='OTH{}'.format(i), tree=TREE_B)
    best[22] = others[:4] + ['B0OWN00004'] + others[4:]
    # 名前にキーワードを含まないが、内容を見て競合・ベンチマークとした商品
    products['B0PICK0001'] = product('B0PICK0001', 'PB己 浴室用 クリーナー', brand='PB己', price=((400, 1500),), sold=((60, 600),), tree=TREE_B)
    products['B0PICK0002'] = product('B0PICK0002', 'PB庚 風呂 洗剤 ジェル', brand='PB庚', price=((400, 1200),), sold=((60, 500),), tree=TREE_B)
    run, store, _, _, _ = make(http=FakeKeepaHttp(products, best, searches))
    run.job_daily()
    store.set('settings/families', {'items': {'B0OWN00004': {'picksAt': '2026-10-02T09:00:00', 'picks': [
        {'asin': 'B0PICK0001', 'why': '競合: 同じ用途'}, {'asin': 'B0PICK0002', 'why': 'ベンチマーク: 売れ筋'},
        {'asin': 'B0SPR00002', 'why': '競合: 価格が近い'}]}}})
    run2, _, _, _, _ = make(store=store, http=FakeKeepaHttp(products, best, searches))
    run2.job_markets()
    kw = [m for m in store.get('views/markets')['items'] if m['by'] == 'keyword']
    assert len(kw) == 1 and kw[0]['path'] == ['競合の提案で集計'] and kw[0]['catId'] == 'kw:B0OWN00004'
    assert kw[0]['name'] == kw[0]['ownNames'][0]                                 # 市場の名前は自社商品の呼び名
    # 市場は「自社商品 + 提案」だけ。キーワードが合うだけの自動の候補は入れない
    assert sorted(r['asin'] for r in kw[0]['top']) == ['B0OWN00004', 'B0PICK0001', 'B0PICK0002', 'B0SPR00002']
    assert {r['asin']: r['peakRev'] for r in kw[0]['top']}['B0PICK0001'] == 900000


def test_products_sharing_proposals_form_one_market():
    from collector.pipeline import Run
    fam = lambda parent, name, picks: {'parent': parent, 'name': name, 'pool': ['OWN' + parent] + picks, 'picks': set(picks)}
    out = Run._merge_curated([
        fam('P1', '長財布 薄型', ['A', 'B', 'C', 'D']),
        fam('P2', '小さい 長財布', ['B', 'C', 'D', 'E']),      # P1 と 3 件重なる → 同じ市場
        fam('P3', '長財布 薄型', ['C', 'D', 'E', 'F']),         # P2 と 3 件重なる → つながって同じ市場
        fam('P4', '耐火バッグ', ['A', 'B', 'X', 'Y']),           # 2 件しか重ならない → 別の市場
    ])
    by = {m['catId']: m for m in out}
    assert set(by) == {'kw:P1', 'kw:P4'}
    wallet = by['kw:P1']
    assert wallet['name'] == '長財布 薄型' and wallet['ownNames'] == ['長財布 薄型', '小さい 長財布', '長財布 薄型']
    assert wallet['asins'][:3] == ['OWNP1', 'OWNP2', 'OWNP3'] and sorted(wallet['asins'][3:]) == list('ABCDEF')
    assert by['kw:P4']['asins'] == ['OWNP4', 'A', 'B', 'X', 'Y'] and by['kw:P4']['by'] == 'keyword'


def test_sales_drop_is_not_reported_while_the_market_is_out_of_season():
    # 自社商品の月間販売は 400 → 200 に減っている。ふだんは「販売数減少」として知らせる
    run, store, _, _, _ = make()
    run.job_daily()
    own = {i['parent']: i for i in store.get('views/own')['items']}
    assert own['B0PARENT01']['status']['label'] == '販売数減少' and not own['B0PARENT01']['seasonal']
    assert any('月間販売' in a['text'] for a in store.get('views/overview')['alerts'])
    name = own['B0PARENT01']['name']

    # 市場の評価で、その商品の市場が「季節あり」（市場ごと売れ行きが落ちている）になった場合は知らせない
    for market in ({'kind': 'own', 'seasonal': True, 'ownNames': [name], 'ownParents': ['B0PARENT01']},
                   {'kind': 'own', 'seasonal': True, 'ownNames': [name]}):                # 以前の形式（商品の一覧がない）
        st = MemoryStore()
        st.set('views/research', {'items': [], 'updatedAt': 'x'})                        # 市場の評価をやり直さない日
        st.set('views/markets', {'items': [market, {'kind': 'compare', 'seasonal': True, 'ownNames': []}]})
        run2, st, _, _, _ = make(store=st)
        run2.job_daily()
        own = {i['parent']: i for i in st.get('views/own')['items']}
        assert own['B0PARENT01']['seasonal'] and own['B0PARENT01']['status']['label'] != '販売数減少'
        assert own['B0PARENT01']['sold30'] == 400 and own['B0PARENT01']['sold'] == 200          # 数字はそのまま見られる
        assert not own['B0OWN00004']['seasonal'] and own['B0OWN00004']['status']['label'] == '評価低下'
        assert not any('月間販売' in a['text'] for a in st.get('views/overview')['alerts'])

    # 季節ありでない市場なら、これまでどおり知らせる
    st = MemoryStore()
    st.set('views/research', {'items': [], 'updatedAt': 'x'})
    st.set('views/markets', {'items': [{'kind': 'own', 'seasonal': False, 'ownNames': [name], 'ownParents': ['B0PARENT01']}]})
    run3, st, _, _, _ = make(store=st)
    run3.job_daily()
    assert {i['parent']: i for i in st.get('views/own')['items']}['B0PARENT01']['status']['label'] == '販売数減少'


def test_market_verdict_lists_what_misses_the_rules():
    from collector.pipeline import Run
    good = {'sizePeak': 8000000, 'over': 1, 'inBand': 7, 'amazon': 0, 'medReviews': 120, 'newWinners': 2}
    assert Run.judge(good) == []
    assert Run.judge(dict(good, sizePeak=150000000, over=9, medReviews=1400)) == ['市場が大きすぎる', '大型商品が多い', 'レビューが多い']
    assert Run.judge(dict(good, sizePeak=900000, inBand=1, newWinners=0)) == ['市場が小さい', '中規模の商品が少ない', '新しい成功例がない']
    assert Run.judge(dict(good, amazon=6, medReviews=None)) == ['Amazon本体の販売が多い']


def test_imported_proposals_become_the_competitor_list():
    run, store, _, _, _ = make()
    run.job_daily()
    assert [c['asin'] for c in store.get('views/comps')['items'] if c['parent'] == 'B0PARENT01'] == ['B0CMP00002', 'B0CMP00003']
    # 画面から提案を取り込む（候補に無い商品、出品がなくなった商品、自社商品を含む）
    products, best, searches = world()
    products['B0BENCH001'] = product('B0BENCH001', 'ベンチマーク クッション 売れ筋', brand='PB先行', sold=((20, 2000),), tree=TREE_A)
    products['B0CMP00020'] = product('B0CMP00020', 'PB20 クッション 丸型', brand='PB20', price=((400, 3000), (5, -1)), tree=TREE_A)
    store.set('settings/families', {'items': {'B0PARENT01': {'picksAt': '2026-10-02T09:00:00', 'picks': [
        {'asin': 'B0CMP00020', 'why': '競合: 同じ形'}, {'asin': 'B0BENCH001', 'why': 'ベンチマーク: この種類でいちばん売れている'},
        {'asin': 'B0OWN00001', 'why': '自社商品は入れない'}, {'asin': 'B0CMP00007', 'why': '競合: 価格が近い'},
        {'asin': 'B0NOTFOUND', 'why': '取得できない商品'}, {'asin': 'B0CMP00003', 'why': '競合'}]}}})
    http = FakeKeepaHttp(products, best, searches)
    run2, _, _, logs, _ = make(store=store, http=http)
    run2.job_candidates()
    doc = store.get('candidates/B0PARENT01')
    assert [p['asin'] for p in doc['picks']] == ['B0CMP00020', 'B0BENCH001', 'B0CMP00007', 'B0NOTFOUND', 'B0CMP00003']
    by = {p['asin']: p for p in doc['picks']}
    assert by['B0BENCH001']['title'].startswith('ベンチマーク') and by['B0BENCH001']['sold'] == 2000 and by['B0BENCH001']['why'].startswith('ベンチマーク')
    assert by['B0NOTFOUND']['missing'] and not by['B0BENCH001']['missing']
    assert [p['asin'] for p in doc['picks'] if p['auto']] == ['B0BENCH001', 'B0CMP00007']     # 出品のない商品は自動では選ばない
    assert doc['items'] and doc['picksAt'] == '2026-10-02T09:00:00'                          # もとの候補も残す（市場の評価で使う）
    watched = [c['asin'] for c in store.get('views/comps')['items'] if c['parent'] == 'B0PARENT01']
    assert watched == ['B0BENCH001', 'B0CMP00007']                                           # 選ぶまでは提案の上位 2 件を監視
    assert any('競合の提案: 1 商品分' in str(x) for x in logs)
    setup = {i['parent']: i for i in store.get('views/setup')['items']}
    assert setup['B0PARENT01']['picks'] == 5 and setup['B0OWN00004']['picks'] == 0

    # 同じ提案をもう一度取りに行かない。利用者が選んだら、その選択を使う。候補を作り直しても提案は残る
    s = store.get('settings/families')
    s['items']['B0PARENT01'].update({'competitors': {'B0CMP00003': {'on': True}}, 'regenAt': '2099-01-01T00:00:00', 'kw': ['クッション'], 'terms': ['低反発 クッション']})
    store.set('settings/families', s)
    http3 = FakeKeepaHttp(products, best, searches)
    run3, _, _, logs3, _ = make(store=store, http=http3)
    run3.job_candidates()
    assert not any('競合の提案' in str(x) for x in logs3)
    assert [c['asin'] for c in store.get('views/comps')['items'] if c['parent'] == 'B0PARENT01'] == ['B0CMP00003']
    assert len(store.get('candidates/B0PARENT01')['picks']) == 5


def test_prices_job_accepts_own_items_saved_by_an_older_version():
    """価格だけの回は、保存済みの自社商品の一覧を使う。古い版が保存した形（7日前との比較）でも止まらない。"""
    run, store, _, _, _ = make()
    run.job_daily()
    own = store.get('views/own')
    for it in own['items']:                              # 古い版の形に戻す
        for key in ('rating30', 'rank30', 'reviews30', 'sold30', 'cmpDays', 'rankNow3'):
            it.pop(key, None)
        it.update({'rating7': 4.3, 'rank7': 1000, 'reviews7': 90, 'rankNow3': 1600, 'rankWeek3': 1000})
    own['items'][0]['status'] = {'sev': 'crit', 'label': '評価低下'}
    own['items'][0]['rating'] = 4.1
    own['items'][1]['status'] = {'sev': 'serious', 'label': 'ランキング急落'}
    store.set('views/own', own)
    for job in ('job_prices', 'job_candidates'):
        run2, _, _, _, _ = make(store=store, now=NOW + timedelta(hours=5))
        getattr(run2, job)()
        texts = ' / '.join(a['text'] + '｜' + (a.get('sub') or '') for a in store.get('views/overview')['alerts'])
        assert '評価が 4.3 → 4.1 に低下｜7日前との比較' in texts and 'ランキング' not in texts


def test_deal_start_is_reported_only_for_competitors_already_watched():
    deal = [{'badge': 'タイムセール', 'dealType': 'LIMITED_TIME_DEAL'}]
    run, store, _, _, _ = make()
    run.job_daily()                                       # 1 日目: B0SPR00002 はセール中だが、監視を始めた日なので通知しない
    assert store.get('state/flags')['items']['B0SPR00002']['quiet'] is True

    # 2 日目: これまで監視していた競合（B0CMP00002）がセールを開始 → 通知する
    day2 = NOW + timedelta(days=1)
    products, best, searches = world(day2)
    products['B0CMP00002']['deals'] = deal
    run2, _, _, _, _ = make(store=store, now=day2, http=FakeKeepaHttp(products, best, searches))
    run2.job_daily()
    texts = [a['text'] for a in store.get('views/overview')['alerts']]
    assert any('PB甲' in t and 'タイムセールを開始' in t for t in texts)
    assert not any('PB戊' in t and 'タイムセール' in t for t in texts)          # 1 日目から続いているセールは出さない

    # 3 日目: 新しく監視に加えた競合がセール中 → 通知しない（競合を入れ替えた日に通知があふれないように）
    day3 = NOW + timedelta(days=2)
    products, best, searches = world(day3)
    products['B0CMP00030']['deals'] = deal
    s = store.get('settings/families') or {'items': {}}
    s['items'].setdefault('B0PARENT01', {})['competitors'] = {'B0CMP00002': {'on': True}, 'B0CMP00030': {'on': True}}
    store.set('settings/families', s)
    run3, _, _, _, _ = make(store=store, now=day3, http=FakeKeepaHttp(products, best, searches))
    run3.job_daily()
    texts = [a['text'] for a in store.get('views/overview')['alerts']]
    assert not any('PB30' in t for t in texts)
    assert 'B0CMP00030' in store.get('state/flags')['known']


def test_many_deal_starts_on_one_day_become_a_single_alert():
    from collector.pipeline import Run
    mk = lambda i, acct: {'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': acct, 'deal': True, 'text': '商品{} がタイムセールを開始'.format(i), 'sub': ''}
    few = Run._collapse_deals([mk(i, 'shop1') for i in range(5)])
    assert len(few) == 5 and all('deal' not in a for a in few)
    other = {'sev': 'warn', 'type': 'promo', 'tab': 'price', 'acct': 'shop1', 'text': 'クーポンを開始', 'sub': ''}
    many = Run._collapse_deals([mk(i, 'shop1') for i in range(8)] + [mk(9, 'shop2'), other])
    assert [a['text'] for a in many] == ['競合 8件がセールを開始', '商品9 がタイムセールを開始', 'クーポンを開始']
    assert many[0]['n'] == 8 and many[0]['acct'] == 'shop1'
