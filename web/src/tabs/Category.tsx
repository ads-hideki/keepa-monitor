import { useState } from 'react';
import LineChart, { DataTable, Legend, type Series } from '../components/LineChart';
import { Arrow, Pill, ProductLink } from '../components/ui';
import { dayLabels } from '../lib/format';
import type { Db } from '../lib/types';

const COLORS = ['--s1', '--s2', '--s3', '--s4'];
const pos = (v: number) => `${v}位`;

export default function Category({ db, acct }: { db: Db; acct: string }) {
  const cats = db.cats.filter(c => acct === 'all' || c.accts.includes(acct));
  const [sel, setSel] = useState<number | null>(null);
  const g = cats.find(c => c.catId === sel) ?? cats[0];
  if (!g) return <section className="card"><p className="empty">このアカウントで監視中のカテゴリはありません</p></section>;

  // 自社を先頭に、あとは現在の順位が良い順に 4 本まで
  const last = (h: (number | null)[]) => h[h.length - 1] ?? 99999;
  const tracks = [...g.tracks].sort((a, b) => (a.kind === 'own' ? 0 : 1) - (b.kind === 'own' ? 0 : 1) || last(a.hist) - last(b.hist)).slice(0, 4);
  const series: Series[] = tracks.map((t, i) => ({ name: (t.kind === 'own' ? '自社 ' : '') + t.name, short: t.kind === 'own' ? '自社' : `競合${i}`, color: COLORS[i], data: t.hist }));
  const labels = dayLabels(30, db.overview?.updatedAt);
  const max = Math.max(10, ...series.flatMap(s => s.data).filter((v): v is number => v != null));
  const top = max <= 10 ? 10 : Math.ceil(max / 10) * 10;
  const ticks = max <= 10 ? [1, 4, 7, 10] : [1, Math.round(top / 3), Math.round((top * 2) / 3), top];

  return (
    <>
      <section className="card">
        <div className="card-h">
          <div>
            <h2>カテゴリ内の順位</h2>
            <p className="sub">売れ筋ランキングを毎日記録し、自社と競合の順位、新規参入を確認します。「{g.name}」は {g.size.toLocaleString('ja-JP')}件中の順位で、記録は {g.days}日分です。</p>
          </div>
          <label className="fld">カテゴリ
            <select value={g.catId} onChange={e => setSel(Number(e.target.value))}>
              {cats.map(c => <option key={c.catId} value={c.catId}>{c.name}</option>)}
            </select>
          </label>
        </div>
        <Legend series={series} />
        <LineChart title={`${g.name}の順位推移（過去30日）`} labels={labels} series={series} invert domain={[1, top]} ticks={ticks} fmt={pos} axisFmt={pos} height={260} />
        <DataTable labels={labels} series={series} fmt={pos} every={3} />
      </section>
      <section className="card">
        <div><h2>「{g.name}」上位10件</h2><p className="sub">変動は7日前との比較です。記録が7日に満たない間は、変動と新規参入を表示しません。</p></div>
        <div className="tw">
          <table className="tbl">
            <thead><tr><th className="n">順位</th><th>商品</th><th className="n">7日前</th><th className="n">変動</th><th>区分</th></tr></thead>
            <tbody>
              {g.top.map(e => {
                const d = e.p7 == null ? null : e.p7 - e.r;
                return (
                  <tr key={e.asin}>
                    <td className="n">{e.r}位</td>
                    <td className="name"><b>{e.title}</b><div className="cellsub">{e.brand || 'ブランド不明'}・<ProductLink asin={e.asin}>{e.asin}</ProductLink></div></td>
                    <td className="n">{!e.hasOld ? <span className="mut">記録なし</span> : e.p7 == null ? <span className="mut">30位より下</span> : `${e.p7}位`}</td>
                    <td className="n">{!e.hasOld ? <span className="mut">記録なし</span> : d == null ? '圏外から' : d === 0 ? <span className="mut">変化なし</span> : <><Arrow dir={d} />{Math.abs(d)}{d > 0 ? ' 上昇' : ' 下落'}</>}</td>
                    <td>{e.kind === 'own' ? <Pill kind="own">自社</Pill> : e.kind === 'comp' ? <Pill kind="neutral">監視中の競合</Pill> : e.kind === 'new' ? <Pill kind="warn">新規参入</Pill> : <span className="mut">その他</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
