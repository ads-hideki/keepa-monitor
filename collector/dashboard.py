# -*- coding: utf-8 -*-
"""既存ダッシュボードから自社商品の一覧を読む（橋渡し）。

ダッシュボードは SP-API で各アカウントの FBA 在庫を取得し、Firestore の
inventory/fba_<アカウント> に {FNSKU: {asin, sku, name, qty, total, inbound}} を保存している。
ここではその 1 アカウント 1 ドキュメントを、1 日 1 回だけ読む（書き込みはしない）。

ダッシュボード側のルールでこのドキュメントは誰でも読めるため、認証情報は使わない。
プロジェクト ID はコードに書かず、環境変数 DASHBOARD_PROJECT_ID で渡す。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

EXCLUDE_NAME_WORDS = ('納品不備',)       # 商品ではない計上専用の ASIN


class DashboardError(Exception):
    pass


def decode(value):
    """Firestore REST の値表現を Python の値にする。"""
    if 'stringValue' in value:
        return value['stringValue']
    if 'integerValue' in value:
        return int(value['integerValue'])
    if 'doubleValue' in value:
        return float(value['doubleValue'])
    if 'booleanValue' in value:
        return bool(value['booleanValue'])
    if 'nullValue' in value:
        return None
    if 'timestampValue' in value:
        return value['timestampValue']
    if 'mapValue' in value:
        return {k: decode(v) for k, v in (value['mapValue'].get('fields') or {}).items()}
    if 'arrayValue' in value:
        return [decode(v) for v in (value['arrayValue'].get('values') or [])]
    return None


def _fetch(project_id, doc_path, api_key=None, timeout=60):
    url = 'https://firestore.googleapis.com/v1/projects/{}/databases/(default)/documents/{}'.format(
        urllib.parse.quote(project_id), doc_path)
    if api_key:
        url += '?key=' + urllib.parse.quote(api_key)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise DashboardError('ダッシュボードの在庫データを読めませんでした（HTTP {}）'.format(e.code))
    except (urllib.error.URLError, OSError) as e:
        raise DashboardError('ダッシュボードに接続できませんでした（{}）'.format(getattr(e, 'reason', e.__class__.__name__)))


def fetch_rows(project_id, accounts, api_key=None, fetch=_fetch):
    """[{account, asin, fnsku, sku, name, qty, total, inbound}] を返す。"""
    if not project_id:
        raise DashboardError('DASHBOARD_PROJECT_ID が設定されていません')
    rows = []
    for acct in accounts:
        doc = fetch(project_id, 'inventory/fba_' + acct, api_key)
        if not doc:
            continue
        data = decode({'mapValue': {'fields': doc.get('fields') or {}}})
        for fnsku, v in (data.get('items') or {}).items():
            v = v or {}
            if not v.get('asin'):
                continue
            rows.append({'account': acct, 'asin': str(v['asin']).strip(), 'fnsku': fnsku,
                         'sku': v.get('sku') or '', 'name': v.get('name') or '',
                         'qty': int(v.get('qty') or 0), 'total': int(v.get('total') or 0),
                         'inbound': int(v.get('inbound') or 0)})
    return rows


def merge_rows(rows):
    """ASIN ごとに 1 件にまとめる。
    - 商品ではない ASIN は除く
    - 同じ ASIN が複数アカウントにあるときは、在庫（入荷予定を含む）が多いアカウントに寄せる
    """
    by = {}
    for r in rows:
        if any(w in r['name'] for w in EXCLUDE_NAME_WORDS):
            continue
        key = (r['asin'], r['account'])
        e = by.setdefault(key, {'account': r['account'], 'asin': r['asin'], 'sku': r['sku'], 'name': r['name'],
                                'qty': 0, 'total': 0, 'inbound': 0})
        e['qty'] += r['qty']
        e['total'] += r['total']
        e['inbound'] += r['inbound']
    best = {}
    for (asin, _), e in by.items():
        cur = best.get(asin)
        if cur is None or (e['total'] + e['inbound']) > (cur['total'] + cur['inbound']):
            best[asin] = e
    for e in best.values():
        e['active'] = (e['total'] + e['inbound']) > 0
    return best
