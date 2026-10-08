import { useState } from 'react';
import { Arrow, matches, Pill, ProductLink, SearchBox, Spark, Thumb } from '../components/ui';
import { num, yen } from '../lib/format';
import type { Db } from '../lib/types';

export default function Catalog({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [q, setQ] = useState('');
  const [only, setOnly] = useState(false);
  const all = db.own.filter(o => acct === 'all' || o.acct === acct);
  const list = all.filter(o => matches(q, o.name, o.title, o.rep, o.parent) && (!only || o.status.sev !== 'good'));
  return (
    <>
      <section className="card">
        <div className="card-h">
          <div>
            <h2>自社カタログの状態</h2>
            <p className="sub">自社 {all.length}商品のうち {list.length}商品を表示。色・サイズ違いは1商品にまとめ、代表の ASIN の値を表示しています。比較は30日前です。</p>
          </div>
          <div className="form">
            <SearchBox value={q} onChange={setQ} />
            <label className="chk"><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} />確認が必要なものだけ</label>
          </div>
        </div>
        <div className="tw">
          <table className="tbl">
            <thead><tr><th>商品</th><th>状態</th><th className="n">価格</th><th className="n">月間販売</th><th className="n">大カテゴリ順位</th><th>30日推移</th><th className="n">評価</th><th className="n">レビュー数</th><th>ページ変更</th></tr></thead>
            <tbody>
              {list.map(o => {
                const rankNow = o.rankNow3 ?? o.rank;
                const d = rankNow != null && o.rank30 != null ? rankNow - o.rank30 : 0;
                const rd = o.rating != null && o.rating30 != null ? o.rating - o.rating30 : 0;
                const sd = (o.sold ?? 0) - (o.sold30 ?? 0);
                const range = o.priceMin != null && o.priceMax != null && o.priceMin !== o.priceMax;
                return (
                  <tr key={o.parent}>
                    <td className="name" title={o.title}>
                      <div className="prod">
                        <Thumb src={o.image} />
                        <div>
                          <b>{o.name}</b>
                          <div className="cellsub">{label(o.acct)}・<ProductLink asin={o.rep}>{o.rep}</ProductLink>・色やサイズ {o.nvar}件{o.cat ? `・${o.cat}` : ''}</div>
                        </div>
                      </div>
                    </td>
                    <td><Pill kind={o.status.sev}>{o.status.label}</Pill></td>
                    <td className="n">
                      {o.price != null ? yen(o.price) : <span className="mut">出品なし</span>}
                      {range && <div className="cellsub">{yen(o.priceMin!)}〜{yen(o.priceMax!)}</div>}
                      {(o.coupon || o.deal) && <div className="cellsub">{[o.coupon && `クーポン ${o.coupon}`, o.deal].filter(Boolean).join('・')}</div>}
                    </td>
                    <td className="n">
                      {o.sold != null ? `${num(o.sold)}点以上` : <span className="mut">表示なし</span>}
                      {o.sold30 != null && <div className="cellsub">{sd === 0 ? '変化なし' : <><Arrow dir={sd} />{o.sold30 ? `${num(o.sold30)}点以上` : '表示なし'} から</>}</div>}
                      {o.seasonal && <div className="cellsub">季節あり（減少は通知しない）</div>}
                    </td>
                    <td className="n">
                      {o.rank != null ? `${num(o.rank)}位` : <span className="mut">不明</span>}
                      {o.rank30 != null && <div className="cellsub">{d === 0 ? '変化なし' : <><Arrow dir={-d} />{num(o.rank30)}位 から</>}</div>}
                    </td>
                    <td><Spark data={o.rankHist} invert /></td>
                    <td className="n">
                      {o.rating != null ? o.rating.toFixed(1) : <span className="mut">不明</span>}
                      <div className="cellsub">{Math.abs(rd) < 0.05 ? '変化なし' : <><Arrow dir={rd} />{o.rating30!.toFixed(1)} から</>}</div>
                    </td>
                    <td className="n">
                      {o.reviews != null ? num(o.reviews) : <span className="mut">不明</span>}
                      {o.reviews != null && o.reviews30 != null && <div className="cellsub">+{o.reviews - o.reviews30}件</div>}
                    </td>
                    <td>
                      {o.changedAt ? `${o.changeWhat || '商品ページ'}（${o.changedAt}）` : <span className="mut">なし</span>}
                      {o.oos > 0 && <div className="cellsub">出品が表示されていない色・サイズ {o.oos}件</div>}
                    </td>
                  </tr>
                );
              })}
              {!list.length && <tr><td colSpan={9} className="empty">該当する商品はありません</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <h2>通知の基準</h2>
        <ul className="notes">
          <li>評価低下: 30日前より 0.2 以上下がったとき</li>
          <li>販売数減少: Amazon が表示する「過去1か月で○点以上購入」が、30日前の表示より 30% 以上減ったとき（30日前に 100点以上だった商品が対象。色・サイズのうち、いちばん多い値で見ます）。市場ごと売れ行きが落ちている「季節あり」の商品は、季節による減少なので通知しません</li>
          <li>ページ変更: タイトルまたはメイン画像が前回の取得時と違うとき（7日間表示）</li>
          <li>出品なしあり: 在庫があるのに出品が表示されていない色・サイズがあるとき</li>
        </ul>
        <p className="sub">ランキングは日ごとの上下が大きいので、通知には使っていません。購入数の表示は 50点・100点きざみの目安で、50点未満の商品には表示されません。</p>
      </section>
    </>
  );
}
