import { useState } from 'react';
import { matches, Pill, ProductLink, SearchBox, Thumb } from '../components/ui';
import type { Db } from '../lib/types';

export default function Stock({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [q, setQ] = useState('');
  const [showIn, setShowIn] = useState(false);
  const all = db.comps.filter(c => !c.pending && (acct === 'all' || c.acct === acct));
  const list = all
    .filter(c => matches(q, c.title, c.brand, c.asin, c.ownName) && (showIn || c.stock === 'out'))
    .sort((a, b) => (a.stock === 'out' ? 0 : 1) - (b.stock === 'out' ? 0 : 1) || (b.outDays || 0) - (a.outDays || 0));
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h2>競合の在庫状況</h2>
          <p className="sub">競合 {all.length}件のうち {list.length}件を表示。新品の出品がない状態を在庫切れとして扱います。残りの数量までは分かりません。</p>
        </div>
        <div className="form">
          <SearchBox value={q} onChange={setQ} />
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
              return (
                <tr key={`${c.parent}/${c.asin}`}>
                  <td className="name">
                    <div className="prod">
                      <Thumb src={c.image} />
                      <div>
                        <b>{c.title}</b>
                        <div className="cellsub">{c.brand || 'ブランド不明'}・<ProductLink asin={c.asin}>{c.asin}</ProductLink>・対 {c.ownName}（{label(c.acct)}）</div>
                      </div>
                    </div>
                  </td>
                  <td>{c.stock === 'out' ? <Pill kind="crit">在庫切れ {c.outDays}日目</Pill> : <Pill kind="neutral">出品あり</Pill>}</td>
                  <td>
                    <div className="strip" role="img" aria-label={`過去30日のうち在庫切れ ${out}日`}>
                      {strip.map((v, i) => <i key={i} className={v === '2' ? 'o' : ''} />)}
                    </div>
                    <div className="cellsub">30日のうち {out}日</div>
                  </td>
                  <td>{c.stock === 'out' ? `自社「${c.ownName}」の広告強化を検討` : <span className="mut">なし</span>}</td>
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
