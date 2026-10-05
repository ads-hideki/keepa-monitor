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
    # 自社: 3色展開の商品（順位が 1000 → 1500 に悪化）と、単品（評価が 4.3 → 4.1 に低下）
    for a in fam:
        p[a] = product(a, '自社ブランド 低反発 クッション 【説明】 椅子用 ' + a[-1], brand='自社ブランド', parent='B0PARENT01', variations=fam,
                       price=((400, 2800),), rank=((400, 1000), (3, 1600)), tree=TREE_A, now=now)
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
    assert '値下げ' in texts and 'クーポンを開始' in texts and '在庫切れ 3日目' in texts and 'タイムセール' in texts
    assert '評価が 4.3 → 4.1' in texts and 'ランキングが 1,000位 → 1,600位' in texts
    assert [a['sev'] for a in ov['alerts']] == sorted([a['sev'] for a in ov['alerts']], key=['crit', 'serious', 'warn', 'good', 'info'].index)
    assert ov['monitor'] == {'families': 2, 'asins': 4, 'competitors': 5, 'unset': 0}
    assert ov['tokens']['spent'] == run.keepa.spent > 0

    cats = {c['catId']: c for c in store.get('views/cats')['items']}
    assert [t['kind'] for t in cats[11]['top'][:4]] == ['other', 'comp', 'own', 'comp'] or cats[11]['top'][2]['kind'] == 'own'
    own_track = [t for t in cats[22]['tracks'] if t['kind'] == 'own'][0]
    assert own_track['hist'][-1] == 5

    sales = store.get('views/sales')
    assert len(sales['months']) == 24 and sales['own']['B0PARENT01'][-1] == 400
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
