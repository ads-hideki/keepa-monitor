import { useMemo, useState } from 'react';
import LineChart, { DataTable, type Series } from '../components/LineChart';
import { Pill, ProductLink, Thumb } from '../components/ui';
import { dateTime, dayLabels, monthLabel, num, parseAsin, yen } from '../lib/format';
import { explain, source } from '../lib/source';
import type { Db, LookupResult } from '../lib/types';

const RECENT_KEY = 'mr-lookup-recent';
const RECENT_MAX = 10;
type Recent = { asin: string; title: string };

/** 最近調べた ASIN（この端末のブラウザにだけ残す。使えない環境では空のまま） */
function loadRecent(): Recent[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') as Recent[]; } catch { return []; }
}
function saveRecent(list: Recent[]) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* 保存できなくても検索は使える */ }
}

/** 万円単位で。推定値なので細かい桁は出さない */
const man = (v: number) => (v >= 10000 ? `${num(v / 10000)}万円` : yen(v));
const months = (from: string | null) => {
  if (!from) return null;
  const d = new Date(from);
  return isNaN(d.getTime()) ? null : Math.max(0, Math.floor((Date.now() - d.getTime()) / (30.4 * 86400000)));
};

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="lk-stat">
      <span className="lk-l">{label}</span>
      <span className="lk-v">{value}</span>
      {sub && <span className="lk-s">{sub}</span>}
    </div>
  );
}

export default function Lookup({ db, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [res, setRes] = useState<LookupResult | null>(null);
  const [recent, setRecent] = useState<Recent[]>(loadRecent);

  // 調べた商品が、自社商品や監視中の競合かどうか
  const own = useMemo(() => new Set(db.ownAsins), [db.ownAsins]);
  const ownByParent = useMemo(() => Object.fromEntries(db.own.map(o => [o.parent, o])), [db.own]);
  const watched = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const c of db.comps) (m[c.asin] ??= []).includes(c.ownName) || m[c.asin].push(c.ownName);
    return m;
  }, [db.comps]);

  const run = async (raw: string) => {
    const asin = parseAsin(raw);
    if (!asin) return setMsg('ASIN を読み取れませんでした。10文字の英数字か、Amazon の商品ページの URL を入れてください。');
    setBusy(true); setMsg(''); setInput(asin);
    try {
      const r = await source.lookup(asin);
      setRes(r);
      const next = [{ asin, title: r.item.title.slice(0, 40) }, ...recent.filter(x => x.asin !== asin)].slice(0, RECENT_MAX);
      setRecent(next); saveRecent(next);
    } catch (e) {
      setMsg(e instanceof Error && !(e as { code?: string }).code ? e.message : explain(e));
    }
    setBusy(false);
  };

  const it = res?.item;
  let body = null;
  if (it) {
    const isOwn = own.has(it.asin) || own.has(it.parent);
    const mine = ownByParent[it.parent];
    const comp = watched[it.asin];
    const age = months(it.listedSince);
    const rev = it.price != null && it.sold != null ? it.price * it.sold : null;
    const peakRev = it.price != null && it.soldPeak != null ? it.price * Math.max(it.soldPeak, it.sold ?? 0) : null;
    const days = dayLabels(90, it.fetchedAt);
    const priceS: Series[] = [{ name: '価格（新品）', short: '価格', color: '--s1', data: it.priceHist }];
    const rankS: Series[] = [{ name: '大カテゴリ順位', short: '順位', color: '--s2', data: it.rankHist }];
    const soldS: Series[] = [{ name: '月間販売（購入数の表示）', short: '月間販売', color: '--s3', data: it.soldHist }];
    const mLabels = it.soldMonths.map(monthLabel);
    body = (
      <>
        <section className="card">
          <div className="prod lk-head">
            <Thumb src={it.image} />
            <div>
              <h2><ProductLink asin={it.asin}>{it.title}</ProductLink></h2>
              <p className="sub">{it.brand || 'ブランド不明'}・{it.asin}{it.parent !== it.asin ? `（親 ${it.parent}）` : ''}{it.path.length ? `・${it.path.join(' › ')}` : ''}</p>
              <div className="pills">
                {isOwn && <Pill kind="own">自社商品{mine ? `「${mine.name}」（${label(mine.acct)}）` : ''}</Pill>}
                {comp && <Pill kind="neutral">監視中の競合（自社「{comp[0]}」{comp.length > 1 ? ` ほか${comp.length - 1}` : ''}）</Pill>}
                {it.amazon && <Pill kind="warn">Amazon 本体も販売</Pill>}
              </div>
            </div>
          </div>
          <div className="lk-grid">
            <Stat label="いまの価格" value={it.price != null ? yen(it.price) : <span className="mut">出品なし</span>}
              sub={it.avg90 != null ? `90日平均 ${yen(it.avg90)}` : undefined} />
            <Stat label="クーポン・セール"
              value={it.coupon || it.deal ? <span className="pills">{it.coupon && <Pill kind="neutral">クーポン {it.coupon}</Pill>}{it.deal && <Pill kind="warn">{it.deal.text}</Pill>}</span> : <span className="mut">なし</span>}
              sub={it.deal?.end ? `${it.deal.end} まで` : undefined} />
            <Stat label="月間販売（購入数の表示）" value={it.sold != null ? `${num(it.sold)}点以上` : <span className="mut">表示なし</span>}
              sub={it.soldPeak != null ? `最盛期 ${num(it.soldPeak)}点（過去12か月のよく売れた3か月の平均）` : undefined} />
            <Stat label="推定月商" value={rev != null ? man(rev) : <span className="mut">不明</span>}
              sub={peakRev != null && peakRev !== rev ? `最盛期 ${man(peakRev)}` : '価格 × 月間販売（下限の目安）'} />
            <Stat label="大カテゴリ順位" value={it.rank != null ? `${num(it.rank)}位` : <span className="mut">不明</span>}
              sub={it.rankDrops30 != null ? `30日で順位が上がった回数 ${num(it.rankDrops30)}回` : undefined} />
            <Stat label="評価・レビュー数" value={it.rating != null ? it.rating.toFixed(1) : <span className="mut">不明</span>}
              sub={it.reviews != null ? `${num(it.reviews)}件` : undefined} />
            <Stat label="出品者" value={it.offers != null ? `${num(it.offers)}人` : <span className="mut">不明</span>}
              sub={it.amazon ? 'Amazon 本体を含む' : undefined} />
            <Stat label="発売から" value={age != null ? `${age}か月` : <span className="mut">不明</span>}
              sub={[it.listedSince, it.variations > 1 ? `色・サイズ ${it.variations}件` : ''].filter(Boolean).join('・') || undefined} />
          </div>
          <p className="sub">Keepa の更新 {dateTime(it.updatedAt ?? undefined)}・調べた時刻 {dateTime(it.fetchedAt)}
            {res?.tokensUsed != null ? `・使ったトークン ${num(res.tokensUsed)}` : ''}{res?.tokensLeft != null ? `（残り ${num(res.tokensLeft)}）` : ''}</p>
        </section>
        <section className="card">
          <div><h2>価格の推移（過去90日）</h2><p className="sub">新品の最安値です。線が途切れている期間は出品がありません。</p></div>
          <LineChart title="価格の推移" labels={days} series={priceS} step fmt={yen} axisFmt={num} height={220} />
          <DataTable labels={days} series={priceS} fmt={yen} every={7} />
        </section>
        <section className="card">
          <div><h2>大カテゴリ順位の推移（過去90日）</h2><p className="sub">上ほど売れています。日ごとの上下が大きいので、傾向を見る目安です。</p></div>
          <LineChart title="大カテゴリ順位の推移" labels={days} series={rankS} invert fmt={v => `${num(v)}位`} axisFmt={num} height={220} />
        </section>
        <section className="card">
          <div><h2>月間販売の推移（過去12か月）</h2><p className="sub">Amazon の「過去1か月で○点以上購入」の表示です。表示がない月は 0、記録より前は空白です。</p></div>
          <LineChart title="月間販売の推移" labels={mLabels} series={soldS} step fmt={v => `${num(v)}点以上`} axisFmt={num} height={220} />
          <DataTable labels={mLabels} series={soldS} fmt={v => `${num(v)}点以上`} head="月" />
        </section>
      </>
    );
  }

  return (
    <>
      <section className="card">
        <div>
          <h2>ASIN 検索</h2>
          <p className="sub">Amazon の ASIN か商品ページの URL を入れると、その商品を Keepa で調べます。監視していない商品も調べられます。
            1 回で Keepa のトークンを 8 前後使います。</p>
        </div>
        <form className="form lk-form" onSubmit={e => { e.preventDefault(); run(input); }}>
          <label className="fld">ASIN または商品 URL
            <input type="text" value={input} onChange={e => setInput(e.target.value)} placeholder="例: B0XXXXXXXX" autoComplete="off" spellCheck={false} disabled={busy} />
          </label>
          <button type="submit" className="btn" disabled={busy || !input.trim()}>{busy ? '調べています…' : '調べる'}</button>
        </form>
        {msg && <p className="err" role="alert">{msg}</p>}
        {recent.length > 0 && (
          <div className="lk-recent">
            <span className="cellsub">最近調べた商品</span>
            <div className="pills">
              {recent.map(r => (
                <button type="button" key={r.asin} className="ghost lk-chip" disabled={busy} title={r.title} onClick={() => run(r.asin)}>{r.asin}<small>{r.title}</small></button>
              ))}
            </div>
          </div>
        )}
      </section>
      {body}
    </>
  );
}
