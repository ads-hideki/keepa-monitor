# -*- coding: utf-8 -*-
"""Keepa の商品オブジェクトから、画面と通知に使う値を取り出す。

Keepa の約束事:
- 時刻は「Keepa 分」。Unix 秒 = (分 + 21564000) * 60
- 価格は円の整数。-1 は「その時点で出品がない」
- 評価は 10 倍の整数（43 = 4.3）
- csv[i] は [時刻, 値, 時刻, 値, ...] の変化点の列
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
KEEPA_OFFSET = 21564000

CSV_AMAZON, CSV_NEW, CSV_SALES, CSV_LIST = 0, 1, 3, 4
CSV_COUNT_NEW, CSV_RATING, CSV_REVIEWS = 11, 16, 17


def to_dt(keepa_minutes):
    return datetime.fromtimestamp((keepa_minutes + KEEPA_OFFSET) * 60, tz=JST)


def to_date(keepa_minutes):
    if keepa_minutes is None or keepa_minutes < 0:
        return None
    return to_dt(keepa_minutes).strftime('%Y-%m-%d')


def current(p, i):
    """現在値。-1（なし）と欠損は None。"""
    cur = ((p.get('stats') or {}).get('current')) or []
    if i < len(cur) and isinstance(cur[i], (int, float)) and cur[i] >= 0:
        return cur[i]
    return None


def changes(p, i):
    """csv[i] を [(日時, 値)] にする。"""
    csv = p.get('csv') or []
    c = csv[i] if i < len(csv) else None
    if not c:
        return []
    return [(to_dt(c[k]), c[k + 1]) for k in range(0, len(c) - 1, 2)]


def daily(points, days, today):
    """変化点の列を、today を最後とする days 日分の日次配列にする（各日の最後の値）。
    値が分からない日は None、出品なし(-1)は -1 のまま。"""
    out = [None] * days
    if not points:
        return out
    start = today - timedelta(days=days - 1)
    last = None
    idx = 0
    pts = sorted(points, key=lambda x: x[0])
    for d in range(days):
        day_end = datetime.combine(start + timedelta(days=d), datetime.max.time(), tzinfo=JST)
        while idx < len(pts) and pts[idx][0] <= day_end:
            last = pts[idx][1]
            idx += 1
        out[d] = last
    return out


def value_days_ago(points, n, today):
    """n 日前の終わり時点の値。"""
    if not points:
        return None
    limit = datetime.combine(today - timedelta(days=n), datetime.max.time(), tzinfo=JST)
    val = None
    for t, v in sorted(points, key=lambda x: x[0]):
        if t <= limit:
            val = v
        else:
            break
    return val


def value_at(points, when):
    """when の時点で有効だった値。"""
    val = None
    for t, v in sorted(points, key=lambda x: x[0]):
        if t <= when:
            val = v
        else:
            break
    return val


def compress(series):
    """日次配列を [日の位置, 値, 日の位置, 値, ...] の変化点だけにする（保存サイズを減らすため）。
    Firestore は配列の入れ子を保存できないので、1 本の配列に平らに並べる。"""
    out, prev = [], object()
    for i, v in enumerate(series):
        if v != prev:
            out.extend([i, v])
            prev = v
    return out


def coupon_text(c):
    """クーポン [1回限り, 定期おトク便] を表示用の文字にする。負は%、正は円。"""
    if not c or not c[0]:
        return None
    v = c[0]
    return '{}%OFF'.format(-v) if v < 0 else '{}円OFF'.format(v)


def coupon_started_recently(p, now, hours=36):
    """直近 hours 時間以内にクーポンが始まったか。"""
    h = p.get('couponHistory') or []
    if len(h) < 3 or not (p.get('coupon') or [0])[0]:
        return False
    last_t, last_v = h[-3], h[-2]
    prev_v = h[-5] if len(h) >= 6 else 0
    return bool(last_v) and not prev_v and (now - to_dt(last_t)) <= timedelta(hours=hours)


_COUNTDOWN = re.compile(r'\d{1,2}:\d{2}')


def deal_text(p):
    """セールの表示名。残り時間つきのバッジ（「終了まで: 20:03:57」など）は「タイムセール」にまとめる。"""
    for d in p.get('deals') or []:
        if isinstance(d, dict):
            badge = (d.get('badge') or '').strip()
            if not badge:
                return 'セール'
            if badge.startswith('終了まで') or _COUNTDOWN.search(badge):
                return 'タイムセール'
            return badge
    return None


def variation_asins(p):
    out = [v['asin'] for v in (p.get('variations') or []) if isinstance(v, dict) and v.get('asin')]
    out += [a.strip() for a in (p.get('variationCSV') or '').split(',') if a.strip()]
    return sorted(set(out))


def variation_label(p, asin):
    for v in p.get('variations') or []:
        if isinstance(v, dict) and v.get('asin') == asin:
            return ' / '.join(str(a.get('value')) for a in (v.get('attributes') or []) if a.get('value'))
    return ''


def monthly_sold(p):
    """月ごとの「過去1か月で○点以上購入」。{'2026-09': 1000, ...}（各月の最後の値）。表示がない月は 0。"""
    h = p.get('monthlySoldHistory') or []
    out = {}
    for i in range(0, len(h) - 1, 2):
        v = h[i + 1]
        out[to_dt(h[i]).strftime('%Y-%m')] = v if isinstance(v, int) and v > 0 else 0      # -1 は「表示なし」
    return out


def month_series(by_month, months):
    """months（'YYYY-MM' の列）に合わせた配列。値がない月は直前の値を引き継ぐ。"""
    keys = sorted(by_month)
    out, last = [], None
    for m in months:
        for k in keys:
            if k <= m:
                last = by_month[k]
        out.append(last)
    return out


def out_of_stock_days(p, today):
    """新品の出品がない状態が続いている日数。出品があれば 0。"""
    pts = changes(p, CSV_NEW)
    if current(p, CSV_NEW) is not None or not pts:
        return 0
    since = None
    for t, v in sorted(pts, key=lambda x: x[0]):
        if v < 0:
            since = since or t
        else:
            since = None
    if since is None:
        return 1
    return max(1, (today - since.date()).days + 1)


def dips(p, today, days=365, min_pct=7, base_days=30):
    """一時的な値下げ（その前30日の中央値より min_pct% 以上安く、あとで戻ったもの）。"""
    series = [v if v and v > 0 else None for v in daily(changes(p, CSV_NEW), days, today)]
    out, i = [], base_days
    while i < len(series):
        window = sorted(v for v in series[i - base_days:i] if v)
        v = series[i]
        if not window or not v:
            i += 1
            continue
        base = window[len(window) // 2]
        if v <= base * (1 - min_pct / 100.0):
            j, low = i, v
            while j + 1 < len(series) and series[j + 1] and series[j + 1] <= base * (1 - min_pct / 100.0):
                j += 1
                low = min(low, series[j])
            if j + 1 < len(series) and j - i < 45:        # 戻ったものだけ（恒久的な値下げは除く）
                start = today - timedelta(days=len(series) - 1 - i)
                end = today - timedelta(days=len(series) - 1 - j)
                out.append({'from': start.strftime('%Y-%m-%d'), 'to': end.strftime('%Y-%m-%d'),
                            'base': base, 'low': low, 'pct': round((1 - low / base) * 100)})
            i = j + base_days // 2
        else:
            i += 1
    return out[-8:]


def fingerprint(p):
    """商品ページの変更検知用。タイトルとメイン画像から作る。"""
    images = p.get('images') or []
    img = ''
    if images and isinstance(images[0], dict):
        img = images[0].get('l') or images[0].get('m') or ''
    title = p.get('title') or ''
    return {'title': hashlib.sha1(title.encode('utf-8')).hexdigest()[:12],
            'image': hashlib.sha1(img.encode('utf-8')).hexdigest()[:12]}


def image_url(p):
    images = p.get('images') or []
    if images and isinstance(images[0], dict):
        f = images[0].get('m') or images[0].get('l')
        if f:
            return 'https://m.media-amazon.com/images/I/' + f
    return None


def brief(p):
    """一覧表示に使う現在値。"""
    rating = current(p, CSV_RATING)
    offers = (p.get('stats') or {}).get('totalOfferCount')
    if not isinstance(offers, int) or offers < 0:
        offers = current(p, CSV_COUNT_NEW)
    tree = p.get('categoryTree') or []
    return {
        'asin': p.get('asin'),
        'title': (p.get('title') or '')[:120],
        'brand': p.get('brand') or '',
        'parent': p.get('parentAsin') or p.get('asin'),
        'price': current(p, CSV_NEW),
        'listPrice': current(p, CSV_LIST),
        'rank': current(p, CSV_SALES),
        'rating': (rating / 10.0) if rating is not None else None,
        'reviews': current(p, CSV_REVIEWS),
        'sold': p.get('monthlySold') if isinstance(p.get('monthlySold'), int) and p.get('monthlySold') > 0 else None,
        'coupon': coupon_text(p.get('coupon')),
        'deal': deal_text(p),
        'amazonSells': current(p, CSV_AMAZON) is not None,
        'offers': offers,
        'image': image_url(p),
        'cat': {'id': tree[-1].get('catId'), 'name': tree[-1].get('name')} if tree else None,
    }


# ---- 商品名から表示名・キーワードを作る ----
_BRACKETS = re.compile(r'【[^】]*】|『[^』]*』|「[^」]*」|\[[^\]]*\]|［[^］]*］|（[^）]*）|\([^)]*\)')


def title_tokens(title, brand=''):
    s = _BRACKETS.sub(' ', title or '')
    drop = {x.lower() for x in re.split(r'[\s　()（）]+', brand or '') if x}
    out = []
    for x in re.split(r'[\s　・/,、]+', s):
        x = x.strip()
        if len(x) >= 2 and x.lower() not in drop and x not in out:
            out.append(x)
    return out


def short_name(title, brand=''):
    t = title_tokens(title, brand)
    if not t:
        return (title or '')[:20]
    return (t[0] if len(t[0]) >= 8 or len(t) == 1 else t[0] + ' ' + t[1])[:28]


def distinguish_names(fams):
    """同じ表示名の商品が複数あるとき、商品名の中の違う語を足して区別する。違いが見つからなければ ASIN の末尾を付ける。

    fams は {親ASIN: {'name', 'title', 'brand', 'rep', ...}}。'name' をその場で書き換える。
    """
    groups = {}
    for key, f in fams.items():
        groups.setdefault(f['name'], []).append(key)
    for name, keys in groups.items():
        if len(keys) < 2:
            continue
        toks = {k: [t for t in title_tokens(fams[k]['title'], fams[k]['brand']) if t not in name.split(' ')] for k in keys}
        taken = set()
        for k in sorted(keys):
            others = [set(toks[o]) for o in keys if o != k]
            extra = next((t for t in toks[k] if not all(t in o for o in others) and (name + ' ' + t) not in taken), None)
            new = (name + ' ' + extra)[:34] if extra else None
            if not new or new in taken:
                new = '{}（{}）'.format(name, (fams[k].get('rep') or k)[-4:])
            taken.add(new)
            fams[k]['name'] = new


def auto_keywords(title, brand, other_titles, lo=0.10, limit=2):
    """自社の商品名のうち、同じカテゴリの商品名にもよく出てくる語を、商品名の順に選ぶ。
    初期値として使い、画面で直せるようにする。"""
    toks = title_tokens(title, brand)
    n = len(other_titles)
    if not n:
        return toks[:limit]
    picked = []
    for x in toks:
        df = sum(1 for t in other_titles if x in (t or '')) / float(n)
        if df >= lo:
            picked.append(x)
        if len(picked) >= limit:
            break
    return picked or toks[:1]
