import { useState } from 'react';
import { matches, Pill, ProductLink, SearchBox, Thumb } from '../components/ui';
import type { CompItem, Db } from '../lib/types';

/** これより長く出品がない商品は、在庫切れではなく販売終了の可能性が高いので、既定では表示しない。 */
const LONG_DAYS = 30;

type Row = CompItem & { owns: string[] };

export default function Stock({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [q, setQ] = useState('');
  const [showIn, setShowIn] = useState(false);
  const [showLong, setShowLong] = useState(false);
  // 同じ競合を複数の自社商品で監視していても、1 行にまとめる
  const byAsin = new Map<string, Row>();
  for (const c of db.comps) {
    if (c.pending || (acct !== 'all' && c.acct !== acct)) continue;
    const own = `${c.ownName}（${label(c.acct)}）`;
    const row = byAsin.get(c.asin);
    if (row) { if (!row.owns.includes(own)) row.owns.push(own); } else byAsin.set(c.asin, { ...c, owns: [own] });
  }
  const all = [...byAsin.values()];
  const isLong = (c: Row) => c.stock === 'out' && (c.outDays || 0) > LONG_DAYS;
  const nLong = all.filter(isLong).length;
  const list = all
    .filter(c => matches(q, c.title, c.brand, c.asin, ...c.owns))
    .filter(c => (c.stock === 'out' ? (showLong || !isLong(c)) : showIn))
    .sort((a, b) => (a.stock === 'out' ? 0 : 1) - (b.stock === 'out' ? 0 : 1) || Number(isLong(a)) - Number(isLong(b)) || (a.outDays || 0) - (b.outDays || 0));
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h2>競合の在庫状況</h2>
          <p className="sub">競合 {all.length}件のうち {list.length}件を表示。新品の出品がない状態を在庫切れとして扱います。残りの数量までは分かりません。</p>
        </div>
        <div className="form">
          <SearchBox value={q} onChange={setQ} />
          <label className="chk"><input type="checkbox" checked={showLong} onChange={e => setShowLong(e.target.checked)} />長期の出品なし（{LONG_DAYS + 1}日以上・{nLong}件）も表示</label>
          <label className="chk"><input type="checkbox" checked={showIn} onChange={e => setShowIn(e.target.checked)} />在庫ありの競合も表示</label>
        </div>
      </div>
      <div className="strip-k"><span><i />出品あり</span><span><i className="o" />在庫切れ</span></div>
      <div className="tw">
        <table className="tbl">
          <thead><tr><th>競合商品</th><th>状態</th><th>過去30日</th><th>対応の目安</th></tr></thead>
          <tbody>
            {list.map(c => {
              const strip = (c.strip || '').padStart(30, '0').split('');
              const out = strip.filter(v => v === '2').length;
              const long = isLong(c);
              return (
                <tr key={c.asin}>
                  <td className="name">
                    <div className="prod">
                      <Thumb src={c.image} />
                      <div>
                        <b>{c.title}</b>
                        <div className="cellsub">{c.brand || 'ブランド不明'}・<ProductLink asin={c.asin}>{c.asin}</ProductLink>・対 {c.owns.join('、')}</div>
                      </div>
                    </div>
                  </td>
                  <td>{c.stock !== 'out' ? <Pill kind="neutral">出品あり</Pill> : long ? <Pill kind="neutral">出品なし {c.outDays}日</Pill> : <Pill kind="crit">在庫切れ {c.outDays}日目</Pill>}</td>
                  <td>
                    <div className="strip" role="img" aria-label={`過去30日のうち在庫切れ ${out}日`}>
                      {strip.map((v, i) => <i key={i} className={v === '2' ? 'o' : ''} />)}
                    </div>
                    <div className="cellsub">30日のうち {out}日</div>
                  </td>
                  <td>{c.stock !== 'out' ? <span className="mut">なし</span> : long ? '販売終了の可能性があります。競合の設定で外すことを検討' : `自社「${c.owns[0].replace(/（[^）]*）$/, '')}」${c.owns.length > 1 ? ` ほか${c.owns.length - 1}商品` : ''}の広告強化を検討`}</td>
                </tr>
              );
            })}
            {!list.length && <tr><td colSpan={4} className="empty">{showIn ? '該当する競合はありません' : '在庫切れの競合はありません'}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
