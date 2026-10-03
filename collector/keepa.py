# -*- coding: utf-8 -*-
"""Keepa API クライアント。

- トークンが足りないときは回復を待ってから続ける（毎分の回復量は API の応答から読む）。
- API キーを含む URL は、ログにも例外にも出さない。このリポジトリは公開なので、
  ログには件数とトークン数だけを書き、商品名や ASIN は書かない。
"""
import gzip
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://api.keepa.com/'
DOMAIN_JP = 5
BATCH = 100


class KeepaError(Exception):
    pass


def _http(method, url, body=None, timeout=120):
    """(HTTPステータス, JSON) を返す。"""
    headers = {'Accept-Encoding': 'gzip', 'User-Agent': 'keepa-monitor/1.0'}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw, enc, status = res.read(), res.headers.get('Content-Encoding', ''), res.status
    except urllib.error.HTTPError as e:
        raw, enc, status = e.read(), e.headers.get('Content-Encoding', ''), e.code
    except (urllib.error.URLError, OSError) as e:
        raise KeepaError('Keepa に接続できませんでした（{}）'.format(getattr(e, 'reason', e.__class__.__name__)))
    if 'gzip' in (enc or '').lower():
        raw = gzip.decompress(raw)
    try:
        return status, json.loads(raw.decode('utf-8'))
    except ValueError:
        raise KeepaError('Keepa の応答を読み取れませんでした（HTTP {}）'.format(status))


class Keepa:
    def __init__(self, key, domain=DOMAIN_JP, http=_http, sleep=time.sleep, clock=time.monotonic,
                 log=print, max_runtime_s=5 * 3600):
        if not key:
            raise KeepaError('KEEPA_API_KEY が設定されていません')
        self._key = key
        self.domain = domain
        self._http = http
        self._sleep = sleep
        self._clock = clock
        self._log = log
        self._deadline = clock() + max_runtime_s
        self.tokens_left = None
        self.refill_rate = 25
        self.refill_in_ms = 60000
        self.spent = 0
        self.by_label = {}

    # ---- 内部 ----
    def _url(self, path, params):
        q = dict(params or {})
        q['key'] = self._key
        return BASE + path + '?' + urllib.parse.urlencode(q)

    def _absorb(self, data, label):
        if 'tokensLeft' in data:
            self.tokens_left = data.get('tokensLeft')
        if data.get('refillRate'):
            self.refill_rate = data['refillRate']
        if data.get('refillIn') is not None:
            self.refill_in_ms = data['refillIn']
        used = int(data.get('tokensConsumed') or 0)
        self.spent += used
        if used:
            self.by_label[label] = self.by_label.get(label, 0) + used
        return used

    def status(self):
        status, data = self._http('GET', self._url('token', {}))
        if status != 200:
            raise KeepaError(self._describe(status, data, 'トークン確認'))
        self._absorb(data, 'token')
        return self.tokens_left

    def _wait_for(self, need):
        """need トークンたまるまで待つ。"""
        for _ in range(240):
            if self.tokens_left is not None and self.tokens_left >= need:
                return
            short = need - (self.tokens_left or 0)
            minutes = max(1, math.ceil(short / max(1, self.refill_rate)))
            wait = min(900, (self.refill_in_ms or 60000) / 1000.0 + (minutes - 1) * 60 + 2)
            if self._clock() + wait > self._deadline:
                raise KeepaError('実行時間の上限に達したため中断しました（トークン回復待ち）')
            self._log('  トークン回復待ち: 約{}秒（残り {} / 必要 {}）'.format(int(wait), self.tokens_left, need))
            self._sleep(wait)
            self.status()
        raise KeepaError('トークンが回復しませんでした')

    def ensure(self, need):
        if self.tokens_left is None:
            self.status()
        if self.tokens_left < need:
            self._wait_for(need)

    def _describe(self, status, data, label):
        err = (data or {}).get('error') or {}
        hint = {402: 'APIキーが無効か、契約が有効ではありません。', 429: 'トークンが不足しています。'}.get(status, '')
        return '{}: HTTP {} {} {} {}'.format(label, status, err.get('type', ''), err.get('message', ''), hint).strip()

    def _call(self, path, params, label, need, method='GET', body=None):
        self.ensure(need)
        for _ in range(4):
            status, data = self._http(method, self._url(path, params), body)
            used = self._absorb(data, label)
            if status == 200 and not data.get('error'):
                self._log('  {}: {} トークン（残り {}）'.format(label, used, self.tokens_left))
                return data
            if status == 429:
                self._wait_for(max(need, 1))
                continue
            raise KeepaError(self._describe(status, data, label))
        raise KeepaError('{}: トークン不足が続いたため中断しました'.format(label))

    # ---- 公開メソッド ----
    def products(self, asins, history=False, days=None, rating=True, stats=90, label='商品'):
        """ASIN → 商品オブジェクト の辞書を返す。100件ずつに分けて取得する。"""
        asins = list(dict.fromkeys(a for a in asins if a))
        out = {}
        for i in range(0, len(asins), BATCH):
            chunk = asins[i:i + BATCH]
            params = {'domain': self.domain, 'asin': ','.join(chunk), 'stats': stats,
                      'history': 1 if history else 0, 'rating': 1 if rating else 0}
            if history and days:
                params['days'] = days
            data = self._call('product', params, label, need=len(chunk) * (2 if rating else 1))
            for p in data.get('products') or []:
                if p and p.get('asin') and p.get('title'):
                    out[p['asin']] = p
        return out

    def bestsellers(self, category_id, label='ランキング'):
        data = self._call('bestsellers', {'domain': self.domain, 'category': category_id, 'range': 0}, label, need=50)
        return ((data.get('bestSellersList') or {}).get('asinList')) or []

    def search(self, term, label='検索'):
        data = self._call('search', {'domain': self.domain, 'type': 'product', 'term': term,
                                     'stats': 90, 'rating': 1, 'history': 0}, label, need=15)
        return [p for p in (data.get('products') or []) if p and p.get('asin') and p.get('title')]

    def finder(self, selection, label='リサーチ'):
        data = self._call('query', {'domain': self.domain}, label, need=15, method='POST', body=selection)
        return data.get('asinList') or [], data.get('totalResults')
