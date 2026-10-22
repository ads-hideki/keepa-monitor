/**
 * MARKET RADAR ASIN 検索の中継
 *
 * 画面の「ASIN 検索」から呼ばれ、Keepa で 1 商品を調べて、表示に必要な値だけを返します。
 * Keepa の API キーを画面に置かないために、ここで中継します（キーはスクリプト プロパティにだけ置く）。
 *
 * 呼べるのは、MARKET RADAR にログインしていて、名簿（allowed_users）に載っている人だけです。
 * 画面から送られたログインの証明（ID トークン）で Firestore の名簿を読めるかを確かめ、読めなければ断ります。
 *
 * 準備（起動タイマーと同じ Apps Script のプロジェクトに、このファイルを追加する）:
 *   1. プロジェクトの設定 → スクリプト プロパティに追加する
 *        KEEPA_API_KEY        Keepa の API アクセスキー
 *        FIREBASE_PROJECT_ID  Firebase のプロジェクト ID
 *        LOOKUP_DAILY_MAX     1 日に調べられる回数の上限（省略時 300）
 *   2. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」
 *        次のユーザーとして実行: 自分 / アクセスできるユーザー: 全員
 *      （「全員」でも、上の名簿の確認を通らない呼び出しは断ります）
 *   3. 表示された「ウェブアプリの URL」を、画面の web/.env.local の VITE_LOOKUP_URL に入れてビルドする
 *
 * このファイルを直したときは、デプロイ → デプロイを管理 → 編集 → バージョン「新バージョン」で更新する。
 */
const KEEPA_DOMAIN = 5;                 // amazon.co.jp
const KEEPA_OFFSET = 21564000;          // Keepa の時刻（分）→ Unix 時刻（分）
const CSV_AMAZON = 0, CSV_NEW = 1, CSV_SALES = 3, CSV_COUNT_NEW = 11, CSV_RATING = 16, CSV_REVIEWS = 17;
const DAYS = 90;                        // 価格・順位の推移を返す日数
const MONTHS = 12;                      // 月間販売を返す月数
const EVENT_WORDS = ['プライムデー', 'プライム感謝祭', 'ブラックフライデー', 'サイバーマンデー', '初売り', '新生活', 'スマイルSALE'];

function doPost(e) {
  try {
    const req = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const asin = String(req.asin || '').trim().toUpperCase();
    if (!/^[A-Z0-9]{10}$/.test(asin)) return reply({ ok: false, error: 'ASIN を読み取れませんでした。10文字の英数字か、商品ページの URL を入れてください。' });
    const who = checkUser(String(req.idToken || ''));
    if (!who.ok) return reply(who);
    const count = countToday();
    if (!count.ok) return reply(count);
    return reply(lookup(asin));
  } catch (err) {
    console.error(err);
    return reply({ ok: false, error: '調べられませんでした。時間をおいてもう一度お試しください。' });
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function prop(name) {
  return PropertiesService.getScriptProperties().getProperty(name);
}

/** ログインの証明で、Firestore の名簿（自分の分）を読めるかを確かめる。読めるのは、正しくログインしていて名簿に載っている人だけ。 */
function checkUser(idToken) {
  const project = prop('FIREBASE_PROJECT_ID');
  if (!project) return { ok: false, error: '中継の設定（FIREBASE_PROJECT_ID）がありません。' };
  const parts = idToken.split('.');
  if (parts.length !== 3) return { ok: false, error: 'ログインし直してください。' };
  let uid = '';
  try {
    uid = JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(parts[1])).getDataAsString()).user_id || '';
  } catch (err) {
    return { ok: false, error: 'ログインし直してください。' };
  }
  if (!/^[A-Za-z0-9]{1,128}$/.test(uid)) return { ok: false, error: 'ログインし直してください。' };
  const url = 'https://firestore.googleapis.com/v1/projects/' + project + '/databases/(default)/documents/allowed_users/' + uid;
  const res = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + idToken }, muteHttpExceptions: true });
  const code = res.getResponseCode();
  if (code === 200) return { ok: true };
  if (code === 401) return { ok: false, error: 'ログインの有効期限が切れました。画面を再読み込みしてください。' };
  return { ok: false, error: 'この ID には ASIN 検索の許可がありません。' };
}

/** 1 日に調べる回数の上限。Keepa のトークンを使い切らないため。 */
function countToday() {
  const max = Number(prop('LOOKUP_DAILY_MAX') || 300);
  const key = 'LOOKUP_' + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMdd');
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const props = PropertiesService.getScriptProperties();
    const n = Number(props.getProperty(key) || 0);
    if (n >= max) return { ok: false, error: '今日の ASIN 検索の上限（' + max + '回）に達しました。明日またお試しください。' };
    props.setProperty(key, String(n + 1));
    // 前の日の回数は消しておく
    Object.keys(props.getProperties()).forEach(function (k) { if (k.indexOf('LOOKUP_') === 0 && k !== key && /\d{8}$/.test(k)) props.deleteProperty(k); });
    return { ok: true, used: n + 1, max: max };
  } finally {
    lock.releaseLock();
  }
}

function lookup(asin) {
  const key = prop('KEEPA_API_KEY');
  if (!key) return { ok: false, error: '中継の設定（KEEPA_API_KEY）がありません。' };
  // 出品者情報（offers）も取る。クーポンとセールの情報は、これを取ったときにだけ最新になるため
  const url = 'https://api.keepa.com/product?key=' + encodeURIComponent(key) + '&domain=' + KEEPA_DOMAIN + '&asin=' + asin +
    '&stats=90&history=1&days=400&rating=1&offers=20&only_live_offers=1';
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  const code = res.getResponseCode();
  let data = {};
  try { data = JSON.parse(res.getContentText()); } catch (err) { data = {}; }
  if (code === 429) {
    const wait = Math.ceil((data.refillIn || 60000) / 60000);
    return { ok: false, error: 'Keepa のトークンが足りません。' + wait + '分ほどしてからお試しください。' };
  }
  if (code !== 200) return { ok: false, error: 'Keepa から取得できませんでした（' + code + '）。' };
  const p = (data.products || [])[0];
  if (!p || !p.title) return { ok: false, error: 'この ASIN の商品は見つかりませんでした。', tokensLeft: data.tokensLeft };
  return { ok: true, item: summarize(p), tokensLeft: data.tokensLeft, tokensUsed: data.tokensConsumed };
}

// ---------------------------------------------------------------- Keepa の値を、画面で使う形にする
function toDate(keepaMinutes) { return new Date((keepaMinutes + KEEPA_OFFSET) * 60000); }

function jstDay(d) { return Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd'); }

function current(p, i) {
  const cur = (p.stats && p.stats.current) || [];
  const v = cur[i];
  return typeof v === 'number' && v >= 0 ? v : null;
}

/** csv[i] の変化点を、今日までの days 日分の日次配列にする（各日の最後の値。出品なしは null）。 */
function daily(p, i, days) {
  const c = (p.csv || [])[i] || [];
  const out = [];
  const today = new Date();
  let k = 0, last = null;
  for (let d = days - 1; d >= 0; d--) {
    const end = jstDay(new Date(today.getTime() - d * 86400000));
    while (k + 1 < c.length && jstDay(toDate(c[k])) <= end) { last = c[k + 1]; k += 2; }
    out.push(typeof last === 'number' && last > 0 ? last : null);
  }
  return out;
}

/** 月ごとの「過去1か月で○点以上購入」（各月の最後の値。表示がない月は 0、記録より前は null）。 */
function monthlySold(p) {
  const h = p.monthlySoldHistory || [];
  const months = [];
  const now = new Date();
  for (let m = MONTHS - 1; m >= 0; m--) {
    const d = new Date(now.getFullYear(), now.getMonth() - m, 1);
    months.push(Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM'));
  }
  const values = months.map(function () { return null; });
  for (let i = 0; i + 1 < h.length; i += 2) {
    const month = Utilities.formatDate(toDate(h[i]), 'Asia/Tokyo', 'yyyy-MM');
    const v = typeof h[i + 1] === 'number' && h[i + 1] > 0 ? h[i + 1] : 0;
    months.forEach(function (m, j) { if (m >= month) values[j] = v; });   // 次の変化まで同じ値が続く
  }
  return { months: months, values: values };
}

function couponText(c) {
  if (!c || !c[0]) return null;
  return c[0] < 0 ? (-c[0]) + '%OFF' : c[0] + '円OFF';
}

function dealInfo(p) {
  const now = Date.now();
  const list = p.deals || [];
  for (let i = 0; i < list.length; i++) {
    const d = list[i] || {};
    const end = typeof d.endTime === 'number' && d.endTime > 0 ? toDate(d.endTime) : null;
    const start = typeof d.startTime === 'number' && d.startTime > 0 ? toDate(d.startTime) : null;
    if ((end && end.getTime() <= now) || (start && start.getTime() > now)) continue;
    const badge = String(d.badge || '').trim();
    const text = !badge ? 'セール' : (badge.indexOf('終了まで') === 0 || /\d{1,2}:\d{2}/.test(badge)) ? 'タイムセール' : badge;
    return { text: text, end: end ? Utilities.formatDate(end, 'Asia/Tokyo', 'M/d HH:mm') : null,
             event: EVENT_WORDS.some(function (w) { return badge.indexOf(w) >= 0; }) };
  }
  return null;
}

function summarize(p) {
  const tree = p.categoryTree || [];
  const img = (p.images || [])[0];
  const rating = current(p, CSV_RATING);
  let offers = p.stats && typeof p.stats.totalOfferCount === 'number' && p.stats.totalOfferCount >= 0 ? p.stats.totalOfferCount : current(p, CSV_COUNT_NEW);
  const avg = (p.stats && p.stats.avg90) || [];
  const listed = typeof p.listedSince === 'number' && p.listedSince > 0 ? toDate(p.listedSince) : null;
  const variations = (p.variationCSV || '').split(',').filter(function (s) { return s.trim(); }).length || (p.variations || []).length;
  const sold = typeof p.monthlySold === 'number' && p.monthlySold > 0 ? p.monthlySold : null;
  const ms = monthlySold(p);
  const peaks = ms.values.filter(function (v) { return v; }).sort(function (a, b) { return b - a; }).slice(0, 3);
  return {
    asin: p.asin, parent: p.parentAsin || p.asin, title: String(p.title || '').slice(0, 200), brand: p.brand || '',
    image: img && (img.m || img.l) ? 'https://m.media-amazon.com/images/I/' + (img.m || img.l) : null,
    category: tree.length ? tree[tree.length - 1].name : null, path: tree.map(function (c) { return c.name; }),
    price: current(p, CSV_NEW), avg90: typeof avg[CSV_NEW] === 'number' && avg[CSV_NEW] > 0 ? avg[CSV_NEW] : null,
    coupon: couponText(p.coupon), deal: dealInfo(p),
    rank: current(p, CSV_SALES), rankDrops30: p.stats && typeof p.stats.salesRankDrops30 === 'number' && p.stats.salesRankDrops30 >= 0 ? p.stats.salesRankDrops30 : null,
    rating: rating !== null ? rating / 10 : null, reviews: current(p, CSV_REVIEWS),
    sold: sold, soldPeak: peaks.length ? Math.round(peaks.reduce(function (a, b) { return a + b; }, 0) / peaks.length) : null,
    soldMonths: ms.months, soldHist: ms.values,
    offers: offers, amazon: current(p, CSV_AMAZON) !== null,
    listedSince: listed ? Utilities.formatDate(listed, 'Asia/Tokyo', 'yyyy-MM-dd') : null,
    variations: variations,
    priceHist: daily(p, CSV_NEW, DAYS), rankHist: daily(p, CSV_SALES, DAYS),
    updatedAt: typeof p.lastUpdate === 'number' && p.lastUpdate > 0 ? toDate(p.lastUpdate).toISOString() : null,
    fetchedAt: new Date().toISOString(),
  };
}
