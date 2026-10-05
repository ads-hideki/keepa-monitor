import { useState } from 'react';
import { ProductLink, Thumb } from '../components/ui';
import { dateTime, num, yen } from '../lib/format';
import { explain, source } from '../lib/source';
import type { Db, ResearchParams } from '../lib/types';

const FIELDS: [keyof ResearchParams, string, number][] = [
  ['priceMin', '価格 下限（円）', 100], ['priceMax', '価格 上限（円）', 100], ['rankMax', 'ランキング 上限（位）', 500],
  ['reviewsMax', 'レビュー数 上限（件）', 10], ['soldMin', '月間販売 下限（点）', 100],
];
const DEFAULTS: ResearchParams = { priceMin: 1500, priceMax: 5000, rankMax: 10000, reviewsMax: 100, soldMin: 300, limit: 30 };

function monthsSince(date: string | null) {
  if (!date) return null;
  const d = new Date(date);
  return Math.max(0, Math.round((Date.now() - d.getTime()) / (30.4 * 86400000)));
}

export default function Research({ db }: { db: Db }) {
  const r = db.research;
  const [prm, setPrm] = useState<ResearchParams>({ ...DEFAULTS, ...(r?.params || {}) });
  const [msg, setMsg] = useState('');
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await source.saveResearch(prm);
      setMsg('条件を保存しました。次の月曜の取得から反映されます。');
    } catch (err) { setMsg(explain(err)); }
  };
  return (
    <section className="card">
      <div>
        <h2>新商品リサーチ</h2>
        <p className="sub">自社商品と同じカテゴリ（いちばん細かい分類）から、条件に合う商品を週に1回（月曜）抽出します。Amazon 本体が販売する商品、出品者の多い商品、自社の商品は結果から除いています。
          {r ? ` 前回の抽出は ${dateTime(r.updatedAt)}。` : ''}</p>
      </div>
      <form className="form" onSubmit={save}>
        {FIELDS.map(([k, label, step]) => (
          <label className="fld" key={k}>{label}
            <input type="number" inputMode="numeric" min={0} step={step} value={prm[k]} onChange={e => setPrm({ ...prm, [k]: Number(e.target.value) || 0 })} />
          </label>
        ))}
        <button type="submit" className="btn">条件を保存</button>
      </form>
      {msg && <p className="sub" role="status">{msg}</p>}
      {r?.error && <p className="banner">{r.error}</p>}
      {!r && <p className="empty">まだ抽出結果がありません。</p>}
      {r && !r.error && (
        <>
          <p className="sub">条件に合う商品 <b>{r.items.length}件</b>（順位の良い順）</p>
          <div className="tw">
            <table className="tbl">
              <thead><tr><th>商品</th><th className="n">価格</th><th className="n">ランキング</th><th className="n">月間販売の目安</th><th className="n">レビュー数</th><th className="n">評価</th><th className="n">発売から</th></tr></thead>
              <tbody>
                {r.items.map(c => {
                  const mon = monthsSince(c.listed);
                  return (
                    <tr key={c.asin}>
                      <td className="name">
                        <div className="prod"><Thumb src={c.image} />
                          <div><b>{c.title}</b><div className="cellsub">{c.brand || 'ブランド不明'}・<ProductLink asin={c.asin}>{c.asin}</ProductLink>{c.cat ? `・${c.cat.name}` : ''}</div></div>
                        </div>
                      </td>
                      <td className="n">{c.price != null ? yen(c.price) : <span className="mut">不明</span>}</td>
                      <td className="n">{c.rank != null ? `${num(c.rank)}位` : <span className="mut">不明</span>}</td>
                      <td className="n">{c.sold != null ? `${num(c.sold)}点以上` : <span className="mut">不明</span>}</td>
                      <td className="n">{c.reviews != null ? `${num(c.reviews)}件` : <span className="mut">不明</span>}</td>
                      <td className="n">{c.rating != null ? c.rating.toFixed(1) : <span className="mut">不明</span>}</td>
                      <td className="n">{mon != null ? `${mon}か月` : <span className="mut">不明</span>}</td>
                    </tr>
                  );
                })}
                {!r.items.length && <tr><td colSpan={7} className="empty">条件に合う商品はありませんでした。条件をゆるめてください。</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
