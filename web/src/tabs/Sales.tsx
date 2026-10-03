import { useState } from 'react';
import LineChart, { DataTable, Legend, type Series } from '../components/LineChart';
import { Arrow, Pill } from '../components/ui';
import { monthLabel, num, yen } from '../lib/format';
import type { Db } from '../lib/types';

const COLORS = ['--s1', '--s2', '--s3', '--s4'];
const units = (v: number) => `${num(v)}点以上`;

export default function Sales({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const list = db.own.filter(o => acct === 'all' || o.acct === acct);
  const [sel, setSel] = useState<string | null>(null);
  const s = db.sales;
  const p = list.find(o => o.parent === sel) ?? list[0];
  if (!s || !p) return <section className="card"><p className="empty">まだ販売実績のデータがありません</p></section>;
  const comps = db.comps.filter(c => c.parent === p.parent && !c.pending).slice(0, 3);
  const labels = s.months.map(monthLabel);
  const series: Series[] = [{ name: `自社 ${p.name}`, short: '自社', color: COLORS[0], data: s.own[p.parent] ?? [] },
    ...comps.map((c, i) => ({ name: c.title, short: `競合${i + 1}`, color: COLORS[i + 1], data: s.comps[c.asin] ?? [] }))];
  const n = labels.length;
  const accts = [...new Set(list.map(o => o.acct))];
  const dips = comps.map(c => ({ c, d: s.dips[c.asin] ?? [] }));
  return (
    <>
      <section className="card">
        <div className="card-h">
          <div>
            <h2>月別の販売数（過去24か月）</h2>
            <p className="sub">Amazon の「過去1か月で○点以上購入」の表示の履歴です。値は段階的で、正確な販売数ではありません。売れる時期と競合との差を確認できます。</p>
          </div>
          <label className="fld">自社商品
            <select value={p.parent} onChange={e => setSel(e.target.value)}>
              {accts.map(a => (
                <optgroup key={a} label={label(a)}>
                  {list.filter(o => o.acct === a).map(o => <option key={o.parent} value={o.parent}>{o.name}（{o.rep}）</option>)}
                </optgroup>
              ))}
            </select>
          </label>
        </div>
        <Legend series={series} />
        <LineChart title={`${p.name}と競合の月別販売数`} labels={labels} series={series} step fmt={units} axisFmt={num} height={260} />
        <div className="tw">
          <table className="tbl">
            <thead><tr><th>商品</th><th className="n">{labels[n - 1]}</th><th className="n">前月との差</th><th>最も多かった月</th></tr></thead>
            <tbody>
              {series.map((se, i) => {
                const a = se.data, cur = a[n - 1], prev = a[n - 2];
                const vals = a.filter((v): v is number => v != null);
                const mx = vals.length ? Math.max(...vals) : null;
                const d = cur != null && prev != null ? cur - prev : 0;
                return (
                  <tr key={se.name}>
                    <td className="name"><b>{se.name}</b>{i === 0 && <> <Pill kind="own">自社</Pill></>}</td>
                    <td className="n">{cur != null ? units(cur) : <span className="mut">不明</span>}</td>
                    <td className="n">{d === 0 ? <span className="mut">変化なし</span> : <><Arrow dir={d} />{num(Math.abs(d))}点</>}</td>
                    <td>{mx != null ? `${labels[a.indexOf(mx)]}（${units(mx)}）` : <span className="mut">不明</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <DataTable labels={labels} series={series} fmt={units} head="月" />
        {!comps.length && <p className="sub">この商品には監視中の競合がありません。「競合の設定」で選ぶと比較できます。</p>}
      </section>
      <section className="card">
        <div>
          <h2>競合の一時的な値下げ（過去12か月）</h2>
          <p className="sub">「{p.name}」の競合が、ふだんの価格から 7% 以上下げて、あとで戻した期間です。セールへの参加状況の目安になります。</p>
        </div>
        {dips.every(x => !x.d.length) ? <p className="empty">一時的な値下げは見つかりませんでした</p> : (
          <div className="tw">
            <table className="tbl">
              <thead><tr><th>競合商品</th><th>期間</th><th className="n">ふだんの価格</th><th className="n">値下げ後</th><th>値下げ率</th></tr></thead>
              <tbody>
                {dips.flatMap(({ c, d }) => [...d].reverse().map((x, i) => (
                  <tr key={`${c.asin}-${x.from}`}>
                    <td className="name">{i === 0 ? <b>{c.title}</b> : <span className="mut">同上</span>}</td>
                    <td>{x.from.replace(/-/g, '/')} 〜 {x.to.slice(5).replace('-', '/')}</td>
                    <td className="n">{yen(x.base)}</td>
                    <td className="n">{yen(x.low)}</td>
                    <td><div className="disc"><span>{x.pct}% 値下げ</span><span className="disc-t"><span className="disc-f" style={{ width: `${Math.min(100, (x.pct / 30) * 100)}%` }} /></span></div></td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
