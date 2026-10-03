import { useMemo, useState } from 'react';
import LineChart, { DataTable, Legend, type Series } from '../components/LineChart';
import { Arrow, matches, Pill, Price as PriceCell, ProductLink, SearchBox, Spark, Thumb } from '../components/ui';
import { dayLabels, expand, priceOnly, yen, num } from '../lib/format';
import type { CompItem, Db } from '../lib/types';

const changed = (c: CompItem) => (c.price != null && c.prev != null && c.price !== c.prev) || !!c.couponNew || !!c.deal;
const order = (c: CompItem) => (c.price != null && c.prev != null && c.price < c.prev && !c.deal ? 0 : c.deal ? 1 : c.couponNew ? 2 : c.price != null && c.prev != null && c.price > c.prev ? 3 : 4);
const key = (c: CompItem) => `${c.parent}/${c.asin}`;

export default function Price({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [q, setQ] = useState('');
  const [only, setOnly] = useState(true);
  const [sel, setSel] = useState<string | null>(null);
  const own = useMemo(() => Object.fromEntries(db.own.map(o => [o.parent, o])), [db.own]);
  const list = db.comps.filter(c => !c.pending && (acct === 'all' || c.acct === acct));
  const shown = list.filter(c => matches(q, c.title, c.brand, c.asin, c.ownName) && (!only || changed(c))).sort((a, b) => order(a) - order(b));
  const current = shown.find(c => key(c) === sel) ?? shown[0];
  const pending = db.comps.filter(c => c.pending && (acct === 'all' || c.acct === acct)).length;

  let detail = null;
  if (current) {
    const mine = own[current.parent];
    const labels = dayLabels(90, db.overview?.updatedAt);
    const series: Series[] = [];
    if (mine) series.push({ name: `自社 ${mine.name}`, short: '自社', color: '--s1', data: priceOnly(expand(mine.priceHist, 90)) });
    series.push({ name: current.title, short: '競合', color: '--s2', data: priceOnly(expand(current.hist, 90)) });
    detail = (
      <section className="card" id="detail">
        <div>
          <h2>価格推移（過去90日）</h2>
          <p className="sub">{current.title} と自社「{current.ownName}」の比較。単位は円です。線が途切れている期間は出品がありません。</p>
        </div>
        <Legend series={series} />
        <LineChart title="価格推移" labels={labels} series={series} step fmt={yen} axisFmt={num} />
        <DataTable labels={labels} series={series} fmt={yen} every={7} />
      </section>
    );
  }

  return (
    <>
      <section className="card">
        <div className="card-h">
          <div>
            <h2>競合の価格・販促</h2>
            <p className="sub">監視中の競合 {list.length}件のうち {shown.length}件を表示。商品名を押すと下に価格推移を表示します。
              {pending > 0 && ` ほかに ${pending}件が次回の取得待ちです。`}</p>
          </div>
          <div className="form">
            <SearchBox value={q} onChange={setQ} />
            <label className="chk"><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} />変化があったものだけ</label>
          </div>
        </div>
        <div className="tw">
          <table className="tbl">
            <thead><tr><th>競合商品</th><th className="n">現在価格</th><th className="n">24時間前との差</th><th className="n">自社との差</th><th>クーポン・セール</th><th>90日推移</th></tr></thead>
            <tbody>
              {shown.map(c => {
                const mine = own[c.parent];
                const d = c.price != null && c.prev != null ? c.price - c.prev : 0;
                const g = c.price != null && mine?.price != null ? c.price - mine.price : null;
                return (
                  <tr key={key(c)} className={current && key(c) === key(current) ? 'sel' : ''}>
                    <td className="name">
                      <div className="prod">
                        <Thumb src={c.image} />
                        <div>
                          <button className="rowbtn" aria-pressed={current ? key(c) === key(current) : false} onClick={() => setSel(key(c))}>{c.title}</button>
                          <div className="cellsub">{c.brand || 'ブランド不明'}・<ProductLink asin={c.asin}>{c.asin}</ProductLink>・対 {c.ownName}（{label(c.acct)}）</div>
                        </div>
                      </div>
                    </td>
                    <td className="n"><PriceCell value={c.price} /></td>
                    <td className="n">{d === 0 ? <span className="mut">変化なし</span> : <><Arrow dir={d} />{yen(Math.abs(d))}</>}</td>
                    <td className="n">{g == null ? <span className="mut">不明</span> : g === 0 ? '同額' : g < 0 ? `${yen(-g)} 安い` : `${yen(g)} 高い`}</td>
                    <td>
                      {c.coupon || c.deal ? (
                        <div className="pills">
                          {c.coupon && <Pill kind={c.couponNew ? 'warn' : 'neutral'}>クーポン {c.coupon}{c.couponNew ? '・新規' : ''}</Pill>}
                          {c.deal && <Pill kind="warn">{c.deal}</Pill>}
                        </div>
                      ) : <span className="mut">なし</span>}
                    </td>
                    <td><Spark data={expand(c.hist, 90)} step /></td>
                  </tr>
                );
              })}
              {!shown.length && <tr><td colSpan={6} className="empty">{only ? '変化のあった競合はありません。チェックを外すと全件を表示します。' : '該当する競合はありません'}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {detail}
    </>
  );
}
