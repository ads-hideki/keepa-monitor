import { Fragment, useState } from 'react';
import { Pill, ProductLink } from '../components/ui';
import { dateTime, num, yen } from '../lib/format';
import type { Db, MarketItem } from '../lib/types';

/** 金額を万円単位で。推定値なので細かい桁は出さない。 */
const man = (v: number) => (v >= 10000 ? `${num(v / 10000)}万円` : yen(v));

function Row({ m, open, toggle }: { m: MarketItem; open: boolean; toggle: () => void }) {
  return (
    <Fragment>
      <tr className={open ? 'sel' : ''}>
        <td className="name">
          <button className="rowbtn" aria-expanded={open} onClick={toggle}>{m.name}</button>
          <div className="cellsub">{m.path.slice(0, -1).join(' › ')}{m.ownNames.length ? `${m.path.length > 1 ? '・' : ''}自社: ${m.ownNames.slice(0, 2).join('、')}${m.ownNames.length > 2 ? ` ほか${m.ownNames.length - 2}` : ''}` : ''}</div>
        </td>
        <td>{m.kind === 'own' ? <Pill kind="own">参入済み</Pill> : m.kind === 'compare' ? <Pill kind="neutral">比較用</Pill> : <Pill kind="good">候補</Pill>}</td>
        <td className="n">{man(m.size)}</td>
        <td className="n">{m.inBand}件<div className="cellsub">{m.n}件中{m.over ? `・大型 ${m.over}件` : ''}</div></td>
        <td className="n">{m.big}件<div className="cellsub">うち Amazon 本体 {m.amazon}件</div></td>
        <td className="n">{m.topShare != null ? `${m.topShare}%` : <span className="mut">不明</span>}<div className="cellsub">{m.topBrand || 'ブランド不明'}</div></td>
        <td className="n">{m.medReviews != null ? `${num(m.medReviews)}件` : <span className="mut">不明</span>}</td>
        <td className="n">{m.newWinners}件</td>
      </tr>
      {open && (
        <tr className="sub-r">
          <td colSpan={8}>
            <div className="tw">
              <table className="tbl">
                <thead><tr><th>上位の商品（売れ筋順）</th><th className="n">価格</th><th className="n">月間販売</th><th className="n">推定月商</th><th className="n">レビュー数</th><th className="n">発売から</th><th>区分</th></tr></thead>
                <tbody>
                  {m.top.map((p, i) => (
                    <tr key={p.asin}>
                      <td className="name"><b>{i + 1}. {p.title}</b><div className="cellsub">{p.brand || 'ブランド不明'}・<ProductLink asin={p.asin}>{p.asin}</ProductLink></div></td>
                      <td className="n">{p.price != null ? yen(p.price) : <span className="mut">出品なし</span>}</td>
                      <td className="n">{p.sold != null ? `${num(p.sold)}点以上` : <span className="mut">表示なし</span>}</td>
                      <td className="n">{p.rev ? man(p.rev) : <span className="mut">不明</span>}</td>
                      <td className="n">{p.reviews != null ? `${num(p.reviews)}件` : <span className="mut">不明</span>}</td>
                      <td className="n">{p.months != null ? `${p.months}か月` : <span className="mut">不明</span>}</td>
                      <td>{p.own ? <Pill kind="own">自社</Pill> : p.amazon ? <Pill kind="warn">Amazon本体</Pill> : p.big ? <Pill kind="warn">出品者多い</Pill> : <span className="mut">小規模</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export default function Markets({ db }: { db: Db }) {
  const mk = db.markets;
  const [open, setOpen] = useState<string | null>(null);
  if (!mk) return null;
  const [lo, hi] = mk.band;
  return (
    <section className="card">
      <div>
        <h2>市場の比較</h2>
        <p className="sub">細かいカテゴリを 1 つの市場として、売れ筋上位の顔ぶれを数字にしています。推定月商は「価格 × 月間販売数」で、下限の目安です。
          狙う範囲は 1 商品あたり月商 {man(lo)}〜{man(hi)}。{dateTime(mk.updatedAt)} 時点。市場名を押すと上位の商品を表示します。</p>
      </div>
      <div className="tw">
        <table className="tbl">
          <thead>
            <tr>
              <th>市場</th><th>区分</th><th className="n">上位10の推定月商</th><th className="n">狙う範囲の商品</th>
              <th className="n">大手らしい商品（上位10）</th><th className="n">最大ブランドの占有</th><th className="n">レビュー数（中央値）</th><th className="n">発売1年以内の成功例</th>
            </tr>
          </thead>
          <tbody>
            {mk.items.map(m => <Row key={m.catId} m={m} open={open === m.catId} toggle={() => setOpen(open === m.catId ? null : m.catId)} />)}
            {!mk.items.length && <tr><td colSpan={8} className="empty">まだ評価した市場がありません</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
