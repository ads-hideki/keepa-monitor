import { Fragment, useState } from 'react';
import { Pill, ProductLink } from '../components/ui';
import { dateTime, num, yen } from '../lib/format';
import type { Db, MarketItem } from '../lib/types';

/** 金額を万円単位で。推定値なので細かい桁は出さない。 */
const man = (v: number) => (v >= 10000 ? `${num(v / 10000)}万円` : yen(v));

function Verdict({ m }: { m: MarketItem }) {
  if (!m.fails) return <span className="mut">未判定</span>;
  if (!m.fails.length) return <Pill kind="good">狙い目</Pill>;
  return (
    <>
      {m.fails.length === 1 ? <Pill kind="warn">惜しい</Pill> : <Pill kind="neutral">対象外</Pill>}
      <div className="cellsub">{m.fails.join('・')}</div>
    </>
  );
}

function Row({ m, open, toggle }: { m: MarketItem; open: boolean; toggle: () => void }) {
  const peak = m.sizePeak ?? m.size;
  const notes = [
    peak > m.size * 1.3 ? `いまは ${man(m.size)}` : '',
    m.unknown ? `販売数が不明 ${m.unknown}件` : '',
  ].filter(Boolean);
  const where = m.by === 'keyword' ? 'キーワードで集計' : m.path.slice(0, -1).join(' › ');
  const own = m.ownNames.length ? `自社: ${m.ownNames.slice(0, 2).join('、')}${m.ownNames.length > 2 ? ` ほか${m.ownNames.length - 2}` : ''}` : '';
  return (
    <Fragment>
      <tr className={open ? 'sel' : ''}>
        <td className="name">
          <button className="rowbtn" aria-expanded={open} onClick={toggle}>{m.name}</button>
          <div className="cellsub">{[where, own].filter(Boolean).join('・')}</div>
          <div className="pills">
            {m.kind === 'own' ? <Pill kind="own">参入済み</Pill> : m.kind === 'compare' ? <Pill kind="neutral">比較用</Pill> : <Pill kind="good">候補</Pill>}
            {m.seasonal && <Pill kind="warn">季節あり</Pill>}
          </div>
        </td>
        <td className="vd"><Verdict m={m} /></td>
        <td className="n">{man(peak)}{notes.length > 0 && <div className="cellsub">{notes.join('・')}</div>}</td>
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
                <thead><tr><th>上位の商品（{m.by === 'keyword' ? '月商の大きい順' : '売れ筋順'}）</th><th className="n">価格</th><th className="n">月間販売（いま）</th><th className="n">最盛期</th><th className="n">推定月商（最盛期）</th><th className="n">レビュー数</th><th className="n">発売から</th><th>区分</th></tr></thead>
                <tbody>
                  {m.top.map((p, i) => (
                    <tr key={p.asin}>
                      <td className="name"><b>{i + 1}. {p.title}</b><div className="cellsub">{p.brand || 'ブランド不明'}・<ProductLink asin={p.asin}>{p.asin}</ProductLink></div></td>
                      <td className="n">{p.price != null ? yen(p.price) : <span className="mut">出品なし</span>}</td>
                      <td className="n">{p.sold != null ? (p.est ? <>約{num(p.sold)}点<div className="cellsub">順位の動きから推定</div></> : `${num(p.sold)}点以上`) : <span className="mut">表示なし</span>}</td>
                      <td className="n">{p.peak != null ? `${num(p.peak)}点` : <span className="mut">記録なし</span>}</td>
                      <td className="n">{(p.peakRev ?? p.rev) ? man(p.peakRev ?? p.rev) : <span className="mut">不明</span>}</td>
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
  const [only, setOnly] = useState(false);
  if (!mk) return null;
  const [lo, hi] = mk.band;
  const judged = mk.items.some(m => m.fails);
  const good = mk.items.filter(m => m.fails && !m.fails.length).length;
  const near = mk.items.filter(m => m.fails?.length === 1).length;
  const list = only ? mk.items.filter(m => m.fails && m.fails.length <= 1) : mk.items;
  const r = mk.rules;
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h2>市場の比較</h2>
          <p className="sub">同じ種類の商品の集まりを 1 つの市場として、売れ筋上位の顔ぶれを数字にしています。推定月商は「価格 × 月間販売数」で、下限の目安です。
            季節商品のために、過去12か月でよく売れた3か月の平均（最盛期）で見ています。
            狙う範囲は 1 商品あたり月商 {man(lo)}〜{man(hi)}。{dateTime(mk.updatedAt)} 時点。市場名を押すと上位の商品を表示します。</p>
          {judged && <p>{mk.items.length}市場のうち、狙い目 <b>{good}</b>、惜しい <b>{near}</b>。</p>}
        </div>
        {judged && (
          <div className="form">
            <label className="chk"><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} />狙い目と惜しいだけ</label>
          </div>
        )}
      </div>
      <div className="tw">
        <table className="tbl">
          <thead>
            <tr>
              <th>市場</th><th>判定</th><th className="n">上位10の推定月商</th><th className="n">狙う範囲の商品</th>
              <th className="n">大手らしい商品（上位10）</th><th className="n">最大ブランドの占有</th><th className="n">レビュー数（中央値）</th><th className="n">発売1年以内の成功例</th>
            </tr>
          </thead>
          <tbody>
            {list.map(m => <Row key={m.catId} m={m} open={open === m.catId} toggle={() => setOpen(open === m.catId ? null : m.catId)} />)}
            {!list.length && <tr><td colSpan={8} className="empty">{mk.items.length ? '該当する市場はありません' : 'まだ評価した市場がありません'}</td></tr>}
          </tbody>
        </table>
      </div>
      {r && (
        <details>
          <summary>狙い目の基準</summary>
          <ul className="notes">
            <li>上位10の推定月商が {man(r.sizeMin)}〜{man(r.sizeMax)}（小さすぎず、巨大でもない）</li>
            <li>月商 {man(hi)} を超える大型商品が {r.overMax}件以下</li>
            <li>狙う範囲の商品が {r.inBandMin}件以上</li>
            <li>Amazon 本体が販売する商品が上位10のうち {r.amazonMax}件以下（メーカー品が少ない）</li>
            <li>レビュー数の中央値が {num(r.reviewsMax)}件以下</li>
            <li>発売1年以内で狙う範囲に届いた商品が {r.newMin}件以上</li>
          </ul>
          <p className="sub">すべて満たすと「狙い目」、1つだけ外れると「惜しい」です。市場は、細かいカテゴリの売れ筋で見ています。カテゴリの上位が別の種類の商品ばかりのときは、商品名にキーワードを含む商品を集めて市場としています（「キーワードで集計」と表示）。
            販売数の表示がない商品は、ランキングが上がった回数から推定しています。</p>
        </details>
      )}
    </section>
  );
}
