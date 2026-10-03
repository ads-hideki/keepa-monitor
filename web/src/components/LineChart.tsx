import { useEffect, useRef, useState } from 'react';

export interface Series {
  name: string;
  short?: string;
  color: string;                 // CSS 変数名（--s1 など）
  data: (number | null)[];
}

interface Props {
  title: string;
  labels: string[];
  series: Series[];
  fmt: (v: number) => string;
  axisFmt: (v: number) => string;
  step?: boolean;                // 階段状に描く（価格など、次の変化まで値が続くもの）
  invert?: boolean;              // 上ほど小さい値（順位）
  domain?: [number, number];
  ticks?: number[];
  height?: number;
}

function niceStep(raw: number) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** 2px の線、終点の点、十字線つきのツールチップ。値のない区間は線を切る。左右キーでも動かせる。 */
export default function LineChart({ title, labels, series, fmt, axisFmt, step, invert, domain, ticks, height = 250 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(0);
  const [cur, setCur] = useState(-1);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(260, Math.floor(el.clientWidth))));
    ro.observe(el);
    setW(Math.max(260, Math.floor(el.clientWidth)));
    return () => ro.disconnect();
  }, []);

  const n = labels.length;
  const all = series.flatMap(s => s.data).filter((v): v is number => v != null);
  if (!W || n < 2 || !all.length) {
    return <div className="chart" ref={box}>{W > 0 && <p className="empty">表示できるデータがまだありません</p>}</div>;
  }
  let lo = Math.min(...all), hi = Math.max(...all), tk: number[] = [];
  if (domain && ticks) { [lo, hi] = domain; tk = ticks; }
  else {
    const st = niceStep(((hi - lo) || hi * 0.1 || 1) / 4);
    lo = Math.floor(lo / st) * st; hi = Math.ceil(hi / st) * st;
    if (lo === hi) hi = lo + st;
    for (let v = lo; v <= hi + 1e-9; v += st) tk.push(v);
  }
  const H = height;
  const wide = series.length > 1 && W > 520;
  const m = { t: 14, r: wide ? 58 : 16, b: 28, l: 16 + 7 * axisFmt(hi).length };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const x = (i: number) => m.l + (pw * i) / (n - 1);
  const y = (v: number) => { const t = (v - lo) / (hi - lo); return m.t + (invert ? t : 1 - t) * ph; };

  const path = (data: (number | null)[]) => {
    let d = '', pen = false, prev = 0;
    data.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      if (!pen) d += `M${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      else d += step ? `H${x(i).toFixed(1)}V${y(v).toFixed(1)}` : `L${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true; prev = v;
    });
    void prev;
    return d;
  };
  const lastIndex = (data: (number | null)[]) => { for (let i = data.length - 1; i >= 0; i--) if (data[i] != null) return i; return -1; };
  const ends = series.map(s => { const i = lastIndex(s.data); return i < 0 ? null : { i, v: s.data[i] as number }; });
  const endYs = ends.filter(e => e && e.i === n - 1).map(e => y(e!.v)).sort((a, b) => a - b);
  const labelsFit = wide && endYs.every((v, k) => k === 0 || v - endYs[k - 1] >= 14);

  const want = W < 480 ? 4 : 6;
  const stepX = Math.max(1, Math.round((n - 1) / (want - 1)));
  const xt: number[] = [];
  for (let i = n - 1; i >= 0; i -= stepX) xt.push(i);

  const move = (clientX: number, el: SVGSVGElement) => {
    const r = el.getBoundingClientRect();
    setCur(Math.max(0, Math.min(n - 1, Math.round(((clientX - r.left - m.l) / pw) * (n - 1)))));
  };
  const tipLeft = cur >= 0 ? (x(cur) > W * 0.6 ? undefined : x(cur) + 12) : 0;
  const tipRight = cur >= 0 && x(cur) > W * 0.6 ? W - x(cur) + 12 : undefined;

  return (
    <div className="chart" ref={box}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}。左右キーで移動できます`} tabIndex={0}
        onPointerMove={e => move(e.clientX, e.currentTarget)} onPointerLeave={() => setCur(-1)}
        onFocus={() => setCur(c => (c < 0 ? n - 1 : c))} onBlur={() => setCur(-1)}
        onKeyDown={e => {
          if (e.key === 'ArrowLeft') { setCur(c => Math.max(0, (c < 0 ? n - 1 : c) - 1)); e.preventDefault(); }
          if (e.key === 'ArrowRight') { setCur(c => Math.min(n - 1, (c < 0 ? n - 1 : c) + 1)); e.preventDefault(); }
        }}>
        {tk.map(v => (
          <g key={v}>
            <line x1={m.l} x2={m.l + pw} y1={y(v)} y2={y(v)} className="grid" />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end" className="tick">{axisFmt(v)}</text>
          </g>
        ))}
        {xt.map(i => (
          <text key={i} x={x(i)} y={H - 8} textAnchor={i === n - 1 && !wide ? 'end' : 'middle'} className="tick">{labels[i]}</text>
        ))}
        {series.map(s => (
          <path key={s.name} d={path(s.data)} fill="none" stroke={`var(${s.color})`} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.map((s, k) => ends[k] && (
          <circle key={s.name} cx={x(ends[k]!.i)} cy={y(ends[k]!.v)} r={4} fill={`var(${s.color})`} stroke="var(--surface)" strokeWidth={2} />
        ))}
        {labelsFit && series.map((s, k) => ends[k] && ends[k]!.i === n - 1 && (
          <text key={s.name} x={x(n - 1) + 10} y={y(ends[k]!.v) + 4} className="endlab">{s.short || s.name}</text>
        ))}
        {cur >= 0 && <line x1={x(cur)} x2={x(cur)} y1={m.t} y2={m.t + ph} className="cross" />}
        {cur >= 0 && series.map(s => s.data[cur] != null && (
          <circle key={s.name} cx={x(cur)} cy={y(s.data[cur] as number)} r={4.5} fill={`var(${s.color})`} stroke="var(--surface)" strokeWidth={2} />
        ))}
      </svg>
      {cur >= 0 && (
        <div className="tip" style={{ left: tipLeft, right: tipRight, top: m.t }}>
          <div className="tip-h">{labels[cur]}</div>
          {series.map(s => (
            <div className="tip-r" key={s.name}>
              <i className="key" style={{ ['--k' as string]: `var(${s.color})` }} />
              <b>{s.data[cur] != null ? fmt(s.data[cur] as number) : 'なし'}</b>
              <span>{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <div className="legend">
      {series.map(s => <span key={s.name}><i style={{ ['--k' as string]: `var(${s.color})` }} />{s.name}</span>)}
    </div>
  );
}

/** グラフの値を表でも見られるようにする。 */
export function DataTable({ labels, series, fmt, every = 1, head = '日付' }: { labels: string[]; series: Series[]; fmt: (v: number) => string; every?: number; head?: string }) {
  const idx: number[] = [];
  for (let i = labels.length - 1; i >= 0; i -= every) idx.unshift(i);
  return (
    <details>
      <summary>数値を表で見る</summary>
      <div className="tw">
        <table className="tbl">
          <thead><tr><th>{head}</th>{series.map(s => <th key={s.name} className="n">{s.name}</th>)}</tr></thead>
          <tbody>
            {idx.map(i => (
              <tr key={i}><td>{labels[i]}</td>{series.map(s => <td key={s.name} className="n">{s.data[i] != null ? fmt(s.data[i] as number) : 'なし'}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
