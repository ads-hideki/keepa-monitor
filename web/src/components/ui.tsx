import type { ReactNode } from 'react';
import { yen } from '../lib/format';

export type PillKind = 'crit' | 'serious' | 'warn' | 'good' | 'neutral' | 'own' | 'info';

export function Pill({ kind, children }: { kind: PillKind; children: ReactNode }) {
  return <span className={`pill p-${kind === 'info' ? 'neutral' : kind}`}>{children}</span>;
}

export const SEV_LABEL: Record<string, string> = { crit: '重要', serious: '要確認', warn: '注意', good: '好機', info: 'お知らせ' };

/** 表の中の小さな推移グラフ。数値は同じ行に出ているので、操作はできない飾り。 */
export function Spark({ data, invert, step }: { data: (number | null)[]; invert?: boolean; step?: boolean }) {
  const w = 92, h = 26, p = 3.5;
  const vals = data.filter((v): v is number => v != null && v > 0);
  if (vals.length < 2) return <span className="mut">なし</span>;
  const lo = Math.min(...vals), hi = Math.max(...vals), n = data.length;
  const X = (i: number) => (p + ((w - 2 * p) * i) / (n - 1)).toFixed(1);
  const Y = (v: number) => { const t = hi === lo ? 0.5 : (v - lo) / (hi - lo); return (p + (invert ? t : 1 - t) * (h - 2 * p)).toFixed(1); };
  let d = '', pen = false, prev = 0, last = -1;
  data.forEach((v, i) => {
    if (v == null || v <= 0) { pen = false; return; }
    d += pen ? (step ? `L${X(i)},${Y(prev)}L${X(i)},${Y(v)}` : `L${X(i)},${Y(v)}`) : `M${X(i)},${Y(v)}`;
    pen = true; prev = v; last = i;
  });
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={X(last)} cy={Y(data[last] as number)} r={3} fill="var(--s1)" stroke="var(--surface)" strokeWidth={1.5} />
    </svg>
  );
}

export function Arrow({ dir }: { dir: number }) {
  return dir < 0 ? <span className="arr dn" aria-hidden="true">▼</span> : <span className="arr up" aria-hidden="true">▲</span>;
}

export function Thumb({ src }: { src?: string | null }) {
  return src ? <img className="thumb" src={src} alt="" loading="lazy" referrerPolicy="no-referrer" /> : null;
}

export function Price({ value }: { value: number | null | undefined }) {
  return value == null ? <Pill kind="crit">出品なし</Pill> : <>{yen(value)}</>;
}

export function amazonUrl(asin: string) {
  return `https://www.amazon.co.jp/dp/${asin}`;
}

/** 商品名。Amazon の商品ページを新しいタブで開く。 */
export function ProductLink({ asin, children }: { asin: string; children: ReactNode }) {
  return <a href={amazonUrl(asin)} target="_blank" rel="noreferrer noopener" className="plink">{children}</a>;
}

export function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="fld">検索
      <input type="search" value={value} placeholder="商品名・ASIN" onChange={e => onChange(e.target.value)} />
    </label>
  );
}

export function matches(q: string, ...fields: (string | null | undefined)[]) {
  const t = q.trim().toLowerCase();
  return !t || fields.some(f => (f || '').toLowerCase().includes(t));
}
