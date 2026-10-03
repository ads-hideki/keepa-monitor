export const num = (n: number) => Math.round(n).toLocaleString('ja-JP');
export const yen = (n: number) => num(n) + '円';

/** [位置, 値, 位置, 値, ...] の変化点の列を、長さ n の日次配列に戻す。 */
export function expand(flat: (number | null)[] | undefined, n: number): (number | null)[] {
  const out: (number | null)[] = new Array(n).fill(null);
  if (!flat) return out;
  for (let k = 0; k + 1 < flat.length; k += 2) {
    const from = flat[k] as number;
    const to = k + 2 < flat.length ? (flat[k + 2] as number) : n;
    for (let i = from; i < Math.min(to, n); i++) out[i] = flat[k + 1];
  }
  return out;
}

/** 出品なし（-1）を欠損にする。グラフでは線を切って表す。 */
export const priceOnly = (a: (number | null)[]) => a.map(v => (v != null && v > 0 ? v : null));

/** base（ISO の日時）を最後とする n 日分の「月/日」。 */
export function dayLabels(n: number, base: string | undefined): string[] {
  const end = base ? new Date(base) : new Date();
  const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(d.getDate() - i);
    out.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }
  return out;
}

/** '2026-09' → '26年9月' */
export const monthLabel = (m: string) => `${m.slice(2, 4)}年${Number(m.slice(5, 7))}月`;

export function dateTime(iso: string | undefined): string {
  if (!iso) return '不明';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '不明';
  return `${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function hoursSince(iso: string | undefined): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return isNaN(t) ? null : (Date.now() - t) / 3600000;
}

/** ASIN そのもの、または Amazon の商品 URL から ASIN を取り出す。読み取れなければ null。 */
export function parseAsin(raw: string): string | null {
  const t = raw.trim();
  const m = t.match(/\/(?:dp|gp\/product|product)\/([A-Za-z0-9]{10})(?:[/?#]|$)/);
  const asin = (m ? m[1] : t).toUpperCase();
  return /^[A-Z0-9]{10}$/.test(asin) ? asin : null;
}

export function accountLabels(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of String(import.meta.env.VITE_ACCOUNT_LABELS || '').split(',')) {
    const [k, ...rest] = part.split(':');
    if (k && rest.length) out[k.trim()] = rest.join(':').trim();
  }
  return out;
}
