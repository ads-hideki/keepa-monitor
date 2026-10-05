# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytest

from collector import dashboard, parse
from collector.keepa import Keepa, KeepaError
from collector.store import MemoryStore, StoreError

from fakes import NOW, FakeKeepaHttp, dashboard_fetch, product


def test_daily_series_and_compress():
    p = product('B0X', 't', price=((40, 3000), (10, -1), (5, 2800)))
    d = parse.daily(parse.changes(p, parse.CSV_NEW), 30, NOW.date())
    assert d[0] == 3000 and d[-1] == 2800 and -1 in d
    flat = parse.compress(d)
    assert flat[:2] == [0, 3000] and len(flat) == 6 and all(not isinstance(x, list) for x in flat)


def test_out_of_stock_and_coupon():
    p = product('B0X', 't', price=((40, 3000), (1.2, -1)))
    assert parse.brief(p)['price'] is None and parse.out_of_stock_days(p, NOW.date()) == 2
    assert parse.coupon_text([-10, 0]) == '10%OFF' and parse.coupon_text([200, 0]) == '200円OFF' and parse.coupon_text([0, 0]) is None


def test_dips_ignores_permanent_price_cut():
    temp = product('B0X', 't', price=((300, 3000), (100, 2400), (90, 3000)))
    perm = product('B0Y', 't', price=((300, 3000), (100, 2400)))
    assert [d['pct'] for d in parse.dips(temp, NOW.date())] == [20]
    assert parse.dips(perm, NOW.date()) == []


def test_month_series_carries_forward():
    assert parse.month_series({'2026-01': 100, '2026-03': 300}, ['2025-12', '2026-01', '2026-02', '2026-03']) == [None, 100, 100, 300]


def test_keepa_batches_and_hides_key():
    prods = {'B0{:08d}'.format(i): product('B0{:08d}'.format(i), 't') for i in range(250)}
    http = FakeKeepaHttp(prods)
    logs = []
    k = Keepa('TESTKEY', http=http, sleep=lambda s: http.refill(s), clock=lambda: 0, log=logs.append)
    got = k.products(list(prods), rating=True)
    assert len(got) == 250 and [p for p, _ in http.requests].count('product') == 3
    assert k.spent == 500 and 'TESTKEY' not in '\n'.join(logs)


def test_keepa_error_message_has_no_url():
    def http(method, url, body=None):
        return 402, {'tokensLeft': 0, 'error': {'type': 'paymentRequired', 'message': 'no access'}}
    with pytest.raises(KeepaError) as e:
        Keepa('SECRET123', http=http, log=lambda s: None).status()
    assert 'SECRET123' not in str(e.value) and 'api.keepa.com' not in str(e.value)


def test_keepa_stops_at_runtime_limit():
    http = FakeKeepaHttp({}, tokens=0, rate=0)
    t = [0]

    def sleep(sec):
        t[0] += sec
    k = Keepa('TESTKEY', http=http, sleep=sleep, clock=lambda: t[0], log=lambda s: None, max_runtime_s=600)
    with pytest.raises(KeepaError):
        k.bestsellers(1)


def test_dashboard_decode_and_merge():
    docs = {'inventory/fba_a': {'items': {'F1': {'asin': 'B0A', 'sku': 's', 'name': 'n', 'qty': 1, 'total': 2, 'inbound': 3},
                                          'F2': {'asin': 'B0A', 'sku': 's2', 'name': 'n', 'qty': 1, 'total': 1, 'inbound': 0}}},
            'inventory/fba_b': {'items': {'G1': {'asin': 'B0A', 'sku': 't', 'name': 'n', 'qty': 0, 'total': 0, 'inbound': 0}}}}
    rows = dashboard.fetch_rows('p', ['a', 'b', 'missing'], fetch=dashboard_fetch(docs))
    assert len(rows) == 3
    m = dashboard.merge_rows(rows)
    assert m['B0A']['account'] == 'a' and m['B0A']['total'] == 3 and m['B0A']['active'] is True


def test_store_rejects_shapes_firestore_cannot_save():
    s = MemoryStore()
    with pytest.raises(StoreError):
        s.set('views/x', {'a': [[1, 2]]})
    with pytest.raises(StoreError):
        s.set('views/x', {1: 'a'})
    s.set('views/x', {'a': [{'b': [1, 2]}]})


def test_deal_text_countdown_badge_is_time_sale():
    assert parse.deal_text({'deals': [{'badge': '終了まで: 20:03:57'}]}) == 'タイムセール'
    assert parse.deal_text({'deals': [{'badge': 'タイムセール'}]}) == 'タイムセール'
    assert parse.deal_text({'deals': [{'badge': 'プライム感謝祭'}]}) == 'プライム感謝祭'
    assert parse.deal_text({'deals': [{}]}) == 'セール'
    assert parse.deal_text({}) is None


def test_monthly_sold_treats_missing_badge_as_zero():
    m0 = int(datetime(2026, 8, 10, tzinfo=parse.JST).timestamp() // 60) - parse.KEEPA_OFFSET
    m1 = int(datetime(2026, 9, 10, tzinfo=parse.JST).timestamp() // 60) - parse.KEEPA_OFFSET
    got = parse.monthly_sold({'monthlySoldHistory': [m0, 300, m1, -1]})
    assert got == {'2026-08': 300, '2026-09': 0}
    assert parse.brief({'asin': 'A', 'monthlySold': -1})['sold'] is None


def test_mark_auto_skips_candidates_without_offer():
    from collector.pipeline import mark_auto
    items = [{'group': 'rec', 'price': None}, {'group': 'rec', 'price': 1000}, {'group': 'big', 'price': 900},
             {'group': 'rec', 'price': 1200}, {'group': 'rec', 'price': 1300}]
    assert [i['auto'] for i in mark_auto(items)] == [False, True, False, True, False]


def test_distinguish_names_adds_a_differing_word_or_asin_tail():
    fams = {
        'P1': {'name': 'ショルダーバッグ', 'title': 'ブランド ショルダーバッグ レディース 本革 斜めがけ', 'brand': 'ブランド', 'rep': 'B0AAAA1111'},
        'P2': {'name': 'ショルダーバッグ', 'title': 'ブランド ショルダーバッグ レディース ナイロン 軽量', 'brand': 'ブランド', 'rep': 'B0AAAA2222'},
        'P3': {'name': 'ショルダーバッグ', 'title': 'ブランド ショルダーバッグ レディース 本革 斜めがけ', 'brand': 'ブランド', 'rep': 'B0AAAA3333'},
        'P4': {'name': '財布', 'title': 'ブランド 財布 本革', 'brand': 'ブランド', 'rep': 'B0AAAA4444'},
    }
    parse.distinguish_names(fams)
    names = [f['name'] for f in fams.values()]
    assert len(set(names)) == 4 and fams['P4']['name'] == '財布'
    assert fams['P2']['name'] == 'ショルダーバッグ ナイロン'
    assert all(n.startswith('ショルダーバッグ') for n in names[:3])
