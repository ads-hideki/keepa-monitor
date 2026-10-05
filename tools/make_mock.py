# -*- coding: utf-8 -*-
"""画面用の模擬データを作る。

取得スクリプト（collector）を、架空の商品と Keepa の代用品で 9 日ぶん動かし、
Firestore に書かれるはずの内容を web/public/mock/db.json に保存する。
実際の取得結果と同じ形になるので、画面を Firebase なしで確認できる。

使い方: python tools/make_mock.py
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from collector.keepa import Keepa                      # noqa: E402
from collector.parse import JST                        # noqa: E402
from collector.pipeline import Run                     # noqa: E402
from collector.store import MemoryStore                # noqa: E402
from fakes import Cfg, FakeKeepaHttp, dashboard_fetch, km, product   # noqa: E402

LAST = datetime(2026, 10, 2, 5, 30, tzinfo=JST)
DAYS = 9

# (アカウント, 商品名, 色・サイズの数, カテゴリID, カテゴリ名, 検索語, 価格)
OWN = [
    ('shop1', '低反発 シートクッション 椅子用 腰にやさしい', 3, 11, 'シートクッション', '低反発 シートクッション', 2780),
    ('shop1', 'ランバーサポート 腰当て クッション', 2, 12, 'ランバーサポート', 'ランバーサポート 腰当て', 3280),
    ('shop1', 'フットレスト 足置き デスク下', 1, 13, 'フットレスト', 'フットレスト 足置き', 3980),
    ('shop2', '折りたたみ 収納ボックス フタ付き', 4, 21, '収納ボックス', '折りたたみ 収納ボックス', 2480),
    ('shop2', '衣類 圧縮袋 10枚組', 2, 22, '圧縮袋', '衣類 圧縮袋', 1680),
    ('shop3', 'ネックピロー 低反発 旅行用', 3, 31, 'ネックピロー', 'ネックピロー 低反発', 2980),
    ('shop3', 'ホット アイマスク USB 充電式', 1, 32, 'アイマスク', 'ホット アイマスク', 1980),
    ('shop3', '着圧 ソックス ひざ下', 2, 33, '着圧ソックス', '着圧 ソックス', 1580),
]
ROOTS = {1: (1, 'ホーム&キッチン'), 2: (1, 'ホーム&キッチン'), 3: (3, 'ドラッグストア')}
BIG = ['大手ホーム', '全国ブランド', '老舗メーカー', '量販ブランド']
PB = ['こもれび', 'ゆるり', 'つむぎ', 'ひなた', 'あおば', 'しずく', 'かなで', 'みのり', 'そよぎ', 'はるか', 'なごみ', 'うらら']


def walk(rnd, start, n, pct, lo=1):
    v, out = start, []
    for _ in range(n):
        v = max(lo, int(v * (1 + rnd.uniform(-pct, pct))))
        out.append(v)
    return out


def at(now, when, value):
    return ((now - when).total_seconds() / 86400.0, value)


def history(now, seed, price, rank, reviews, rating=43, sold=400, events=()):
    """絶対日付で決めた履歴を、now から見た「何日前」に直す。"""
    rnd = random.Random(seed)
    base = LAST - timedelta(days=720)
    prices = [(base, price)]
    t = base
    while True:
        t += timedelta(days=rnd.randint(25, 70))
        if t > LAST - timedelta(days=3):
            break
        sale = int(price * rnd.choice([0.8, 0.85, 0.9]) / 10) * 10
        prices += [(t, sale), (t + timedelta(days=rnd.randint(3, 9)), price)]
    ranks = [(LAST - timedelta(days=120 - i), r) for i, r in enumerate(walk(rnd, rank, 121, 0.12))]
    revs = [(LAST - timedelta(days=400 - i * 4), reviews - (100 - i) * max(1, reviews // 150)) for i in range(101)]
    rates = [(base, rating)]
    solds = [(LAST - timedelta(days=30 * (24 - i)), int(max(50, sold * (1 + 0.35 * rnd.uniform(-1, 1))) // 50 * 50)) for i in range(25)]
    for kind, when, value in events:
        {'price': prices, 'rank': ranks, 'rating': rates, 'reviews': revs}[kind].append((when, value))
    cut = lambda pts: tuple(at(now, w, v) for w, v in sorted(pts) if w <= now) or (at(now, base, pts[0][1]),)
    return dict(price=cut(prices), rank=cut(ranks), reviews=cut([(w, max(1, v)) for w, v in revs]), rating=cut(rates), sold=cut(solds))


def world(now):
    rnd = random.Random(7)
    products, best, searches, docs = {}, {}, {}, {}
    for fi, (acct, name, nvar, cat, cat_name, term, price) in enumerate(OWN):
        root = ROOTS[int(str(cat)[0])]
        tree = (root, (cat, cat_name))
        asins = ['B0OWN{:03d}{:02d}'.format(fi, v) for v in range(nvar)]
        parent = 'B0PAR{:05d}'.format(fi) if nvar > 1 else None
        events = []
        if fi == 5:
            events.append(('rating', LAST - timedelta(days=2), 41))                 # 評価低下
        if fi == 1:
            events += [('rank', LAST - timedelta(days=d), 5200 + d * 40) for d in range(4)]   # ランキング急落
        title = '自社{} {}'.format('ABC'[fi % 3], name)
        if fi == 4 and now >= LAST - timedelta(days=1):
            title += ' 【改良版】'                                                  # ページ変更
        for v, a in enumerate(asins):
            h = history(now, 100 + fi, price, 900 + fi * 420, 300 + fi * 210, events=events)
            products[a] = product(a, title, brand='自社' + 'ABC'[fi % 3], parent=parent, variations=asins if parent else None,
                                  tree=tree, coupon=[-5, 0] if fi == 6 else None, now=now, **h)
            docs.setdefault('inventory/fba_' + acct, {'items': {}})['items']['X{}{}'.format(fi, v)] = {
                'asin': a, 'sku': 'SKU-{}-{}'.format(fi, v), 'name': title, 'qty': 40 + v * 15, 'total': 60 + v * 15, 'inbound': 0}
        comps = []
        for j in range(22):
            a = 'B0CMP{:02d}{:03d}'.format(fi, j)
            if j % 6 == 0:
                brand, t, amazon, offers = BIG[(fi + j) % 4], '{} {} 定番'.format(BIG[(fi + j) % 4], name.split(' ')[0] + ' ' + name.split(' ')[1]), 1800, 9 + j
            elif j % 7 == 3:
                brand, t, amazon, offers = PB[(fi + j) % 12], '{} キッチン 収納 ラック'.format(PB[(fi + j) % 12]), None, 1
            else:
                brand = PB[(fi * 5 + j) % 12]
                t, amazon, offers = '{} {} {}'.format(brand, name.split(' ')[0] + ' ' + name.split(' ')[1], rnd.choice(['軽量', '大きめ', 'メッシュ', '洗える', '改良版'])), None, 1
            cp = int(price * rnd.uniform(0.82, 1.25) / 100) * 100 - 20
            ev, coupon, coupon_hist, deals = [], None, None, None
            if fi == 0 and j == 1:
                ev.append(('price', LAST - timedelta(hours=14), cp - 400))            # 値下げ
            if fi == 3 and j == 2:
                ev.append(('price', LAST - timedelta(days=2, hours=3), -1))           # 在庫切れ
            if fi == 5 and j == 1:
                coupon, coupon_hist = [-15, 0], [km(LAST - timedelta(days=40)), 0, 0, km(LAST - timedelta(hours=9)), -15, 0]
            if fi == 6 and j == 2 and now >= LAST - timedelta(hours=1):
                deals = [{'badge': 'タイムセール', 'dealType': 'LIMITED_TIME_DEAL'}]
            h = history(now, 1000 + fi * 50 + j, cp, 400 + j * 260, 40 + (j * 173) % 2600, rating=38 + (j * 3) % 9,
                        sold=200 + (j * 137) % 1500, events=ev)
            products[a] = product(a, t, brand=brand, tree=tree, amazon=amazon, offers=offers, coupon=coupon,
                                  coupon_hist=coupon_hist, deals=deals, now=now, **h)
            comps.append(a)
        day = (now.date() - (LAST - timedelta(days=DAYS - 1)).date()).days
        order = comps[:]
        random.Random(fi * 100 + day).shuffle(order)
        order = sorted(order, key=lambda a: comps.index(a) + (order.index(a) % 3))
        pos = [2, 3, 0, 4, 12, 3, 6, 18][fi] + (1 if day % 4 == 0 else 0)
        order.insert(min(pos, len(order)), asins[0])
        if fi in (0, 3) and now >= LAST - timedelta(hours=1):                          # 新規参入
            a = 'B0NEW{:05d}'.format(fi)
            products[a] = product(a, '新顔ブランド {} 話題'.format(name.split(' ')[0] + ' ' + name.split(' ')[1]), brand='新顔ブランド', tree=tree, now=now,
                                  **history(now, 5000 + fi, price - 300, 600, 12))
            order.insert(6, a)
        best[cat] = order
        searches[term] = [comps[1], comps[2], comps[4], comps[8]]
    finder = []
    for k in range(14):
        a = 'B0RSC{:05d}'.format(k)
        products[a] = product(a, '{} {} {}'.format(PB[k % 12], ['ハニカム クッション', '吊り下げ 収納', '首用 ホットパッド', '冷感 アイマスク', '骨盤 サポーター'][k % 5], ['新作', '軽量', '話題'][k % 3]),
                              brand=PB[k % 12], tree=((1, 'ホーム&キッチン'), (90 + k, 'その他')), now=now,
                              **history(now, 9000 + k, 1800 + k * 260, 1500 + k * 600, 15 + k * 9, sold=300 + k * 60))
        finder.append(a)
    for k, (root, leaf, title) in enumerate([('本', '実用書', '架空出版 片づけの教科書'), ('ペット用品', '食器', 'こはる 猫用 食器 傾斜つき'),
                                              ('スポーツ&アウトドア', 'ヨガマット', 'みのり ヨガマット 厚手')]):
        a = 'B0RSC9{:04d}'.format(k)
        products[a] = product(a, title, brand=title.split(' ')[0], tree=((50 + k, root), (190 + k, leaf)), now=now,
                              **history(now, 800 + k * 300, 1900 + k * 400, 1200 + k * 500, 20 + k * 15, sold=700 - k * 100))
        finder.insert(k * 3, a)
    for p in products.values():
        p['images'] = []            # 架空の商品なので画像は持たせない
    return products, best, searches, docs, finder


class MockCfg(Cfg):
    accounts = ['shop1', 'shop2', 'shop3']


def main():
    store = MemoryStore()
    # 利用者が自分で競合を選んだ商品（手動追加でまだ取得できていない ASIN を含む）
    store.set('settings/families', {'items': {'B0PAR00003': {'competitors': {
        'B0CMP03001': {'on': True}, 'B0CMP03002': {'on': True}, 'B0CMP03004': {'on': False},
        'B0MANUAL01': {'on': True, 'manual': True}}}}})
    store.set('settings/brands', {'excluded': ['量販ブランド']})
    for d in range(DAYS):
        now = LAST - timedelta(days=DAYS - 1 - d)
        products, best, searches, docs, finder = world(now)
        http = FakeKeepaHttp(products, best, searches, finder=finder)
        keepa = Keepa('TESTKEY', http=http, sleep=http.refill, clock=lambda: 0, log=lambda s: None, max_runtime_s=10 ** 9)
        Run(store, keepa, MockCfg(), now=now, log=lambda s: None, dash_fetch=dashboard_fetch(docs)).job_daily()
    keep = {p: v for p, v in store.docs.items() if p.split('/')[0] in ('views', 'candidates', 'settings')}
    out = os.path.join(ROOT, 'web', 'public', 'mock', 'db.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(keep, f, ensure_ascii=False)
    ov = store.get('views/overview')
    print('書き出しました: {} ドキュメント / 通知 {} 件 {} / 監視 {}'.format(len(keep), len(ov['alerts']), ov['counts'], ov['monitor']))


if __name__ == '__main__':
    main()
