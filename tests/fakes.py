# -*- coding: utf-8 -*-
"""テスト用の代用品。商品名や ASIN はすべて架空。"""
import urllib.parse
from datetime import datetime, timedelta

from collector.parse import JST, KEEPA_OFFSET

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=JST)


def km(dt):
    """日時 → Keepa 分"""
    return int(dt.timestamp() // 60) - KEEPA_OFFSET


def pts(pairs, now=NOW):
    """[(何日前, 値)] → Keepa の [時刻, 値, ...]"""
    out = []
    for days_ago, v in sorted(pairs, key=lambda x: -x[0]):
        out += [km(now - timedelta(days=days_ago)), v]
    return out


def product(asin, title, brand='PB', parent=None, variations=None, price=((400, 3000),), rank=((400, 1000),),
            rating=((400, 43),), reviews=((400, 100),), sold=((60, 300), (20, 400)), coupon=None, coupon_hist=None,
            deals=None, amazon=None, offers=1, tree=((1, 'ルート'), (11, 'カテゴリA')), image='img.jpg', now=NOW):
    csv = [None] * 36
    csv[1], csv[3], csv[16], csv[17] = pts(price, now), pts(rank, now), pts(rating, now), pts(reviews, now)
    cur = [-1] * 36
    cur[0] = amazon if amazon else -1
    cur[1] = sorted(price)[0][1]          # 何日前がいちばん小さい = 最新
    cur[3], cur[16], cur[17], cur[11] = sorted(rank)[0][1], sorted(rating)[0][1], sorted(reviews)[0][1], offers
    return {
        'asin': asin, 'title': title, 'brand': brand, 'parentAsin': parent,
        'variations': [{'asin': a, 'attributes': [{'dimension': 'Color', 'value': a[-2:]}]} for a in (variations or [])],
        'csv': csv, 'stats': {'current': cur, 'totalOfferCount': offers},
        'monthlySold': sorted(sold)[0][1] if sold else None, 'monthlySoldHistory': pts(sold, now) if sold else None,
        'coupon': coupon, 'couponHistory': coupon_hist, 'deals': deals,
        'images': [{'l': image, 'm': image}], 'categoryTree': [{'catId': i, 'name': n} for i, n in tree],
        'listedSince': km(now - timedelta(days=200)), 'lastUpdate': km(now),
    }


class FakeKeepaHttp:
    """Keepa API の代わり。トークンの消費と回復もまねる。"""

    def __init__(self, products, bestsellers=None, searches=None, tokens=1500, rate=25, finder=None):
        self.products, self.bestsellers, self.searches = products, bestsellers or {}, searches or {}
        self.tokens, self.rate, self.finder = tokens, rate, finder or []
        self.requests = []
        self.force_429 = 0

    def refill(self, seconds):
        # 応答の refillIn はいつも 30 秒なので、30 秒後に 1 回目、以後 60 秒ごとに回復する
        self.tokens = min(1500, self.tokens + int((seconds + 30) // 60) * self.rate)

    def __call__(self, method, url, body=None):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path.strip('/')
        assert q.get('key') == 'TESTKEY'
        self.requests.append((path, {k: v for k, v in q.items() if k != 'key'}))

        def env(used, **extra):
            self.tokens -= used
            d = {'tokensLeft': self.tokens, 'refillRate': self.rate, 'refillIn': 30000, 'tokensConsumed': used}
            d.update(extra)
            return d

        if path == 'token':
            return 200, env(0)
        if self.force_429:
            self.force_429 -= 1
            return 429, env(0, error={'type': 'notEnoughToken', 'message': ''})
        if path == 'product':
            asins = q['asin'].split(',')
            per = 2 if q.get('rating') == '1' else 1
            if self.tokens < 1:
                return 429, env(0, error={'type': 'notEnoughToken', 'message': ''})
            return 200, env(len(asins) * per, products=[self.products.get(a) for a in asins])
        if path == 'bestsellers':
            lst = self.bestsellers.get(int(q['category']))
            return 200, env(50 if lst else 0, bestSellersList={'asinList': lst} if lst else None)
        if path == 'search':
            return 200, env(5, products=[self.products[a] for a in self.searches.get(q['term'], []) if a in self.products])
        if path == 'query':
            return 200, env(11, asinList=list(self.finder), totalResults=len(self.finder))
        return 404, env(0, error={'type': 'unknown', 'message': path})


def fs_value(v):
    """Python の値 → Firestore REST の値表現"""
    if isinstance(v, bool):
        return {'booleanValue': v}
    if isinstance(v, int):
        return {'integerValue': str(v)}
    if isinstance(v, str):
        return {'stringValue': v}
    if isinstance(v, dict):
        return {'mapValue': {'fields': {k: fs_value(x) for k, x in v.items()}}}
    if isinstance(v, list):
        return {'arrayValue': {'values': [fs_value(x) for x in v]}}
    return {'nullValue': None}


def dashboard_fetch(docs):
    """docs = {'inventory/fba_x': {'items': {...}}} を返す fetch 関数を作る。"""
    def fetch(project_id, doc_path, api_key=None):
        d = docs.get(doc_path)
        if d is None:
            return None
        return {'name': doc_path, 'fields': {k: fs_value(v) for k, v in d.items()}}
    return fetch


class Cfg:
    keepa_key = 'TESTKEY'
    dashboard_project = 'demo-project'
    dashboard_api_key = None
    accounts = ['shop1', 'shop2']
    max_categories = 40
    category_top = 40
    max_runtime_s = 3600
    candidates_per_run = 0
