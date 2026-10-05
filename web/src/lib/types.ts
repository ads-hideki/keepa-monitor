// Firestore に保存されるデータの形。collector/pipeline.py が書く内容と対応する。

export type Sev = 'crit' | 'serious' | 'warn' | 'good' | 'info';
export type TabId = 'overview' | 'price' | 'category' | 'catalog' | 'stock' | 'research' | 'sales' | 'setup';

export interface Alert {
  sev: Sev;
  type: string;
  tab: TabId;
  acct: string | null;
  text: string;
  sub?: string;
  /** 複数の通知を 1 件にまとめたときの件数 */
  n?: number;
}

export interface Overview {
  updatedAt: string;
  job: string;
  alerts: Alert[];
  warnings: string[];
  accounts: string[];
  counts: Record<string, number>;
  monitor: { families: number; asins: number; competitors: number; unset: number };
  tokens: { spent: number; today: number; left: number | null; rate: number; byLabel: Record<string, number>; days: Record<string, number> };
}

export interface OwnItem {
  parent: string;
  acct: string;
  name: string;
  title: string;
  rep: string;
  image: string | null;
  nvar: number;
  cat: string | null;
  price: number | null;
  priceMin: number | null;
  priceMax: number | null;
  priceHist: (number | null)[];
  /** 比較に使う日数（30）。古いデータには無い */
  cmpDays?: number;
  rank: number | null;
  rank30?: number | null;
  rankNow3?: number | null;
  rankHist: (number | null)[];
  rating: number | null;
  rating30?: number | null;
  reviews: number | null;
  reviews30?: number | null;
  /** Amazon が表示する「過去1か月で○点以上購入」。色・サイズのうち、いちばん多い値 */
  sold: number | null;
  sold30?: number | null;
  coupon: string | null;
  deal: string | null;
  changedAt: string | null;
  changeWhat: string | null;
  oos: number;
  status: { sev: Sev; label: string };
}

export interface CompItem {
  asin: string;
  parent: string;
  acct: string;
  ownName: string;
  manual: boolean;
  auto: boolean;
  pending?: boolean;
  title: string;
  brand: string;
  image?: string | null;
  price: number | null;
  prev?: number | null;
  hist?: (number | null)[];
  coupon?: string | null;
  couponNew?: boolean;
  deal?: string | null;
  stock: 'in' | 'out' | 'unknown';
  outDays?: number;
  strip?: string;
  rating?: number | null;
  reviews?: number | null;
  sold?: number | null;
}

export interface CatTop {
  r: number;
  asin: string;
  title: string;
  brand: string;
  p7: number | null;
  kind: 'own' | 'comp' | 'new' | 'other';
  hasOld: boolean;
}
export interface CatTrack {
  key: string;
  name: string;
  kind: 'own' | 'comp';
  hist: (number | null)[];
}
export interface CatItem {
  catId: number;
  name: string;
  size: number;
  parents: string[];
  accts: string[];
  top: CatTop[];
  tracks: CatTrack[];
  days: number;
}

export interface Dip {
  from: string;
  to: string;
  base: number;
  low: number;
  pct: number;
}
export interface Sales {
  updatedAt: string;
  months: string[];
  own: Record<string, (number | null)[]>;
  comps: Record<string, (number | null)[]>;
  dips: Record<string, Dip[]>;
}

export interface ResearchParams {
  priceMin: number;
  priceMax: number;
  rankMax: number;
  reviewsMax: number;
  soldMin: number;
  limit: number;
  /** 対象から外す大カテゴリの名前。1 文字は完全一致、2 文字以上は「含む」で判定 */
  excludeRoots?: string[];
  /** 狙う商品の推定月商の範囲（円） */
  revMin?: number;
  revMax?: number;
}
export interface ResearchItem {
  asin: string;
  title: string;
  brand: string;
  price: number | null;
  rank: number | null;
  rating: number | null;
  reviews: number | null;
  sold: number | null;
  image: string | null;
  cat: { id: number; name: string } | null;
  root?: string;
  listed: string | null;
}
export interface Research {
  updatedAt: string;
  params: ResearchParams;
  items: ResearchItem[];
  error: string | null;
  matched?: number | null;
  /** 取得した候補に含まれていた大カテゴリの名前 */
  roots?: string[];
  sort?: 'sold' | 'rank';
}

export interface MarketProduct {
  asin: string;
  title: string;
  brand: string;
  price: number | null;
  /** いまの月間販売数の目安。Amazon の表示、なければランキングの動きからの推定（est が true） */
  sold: number | null;
  est?: boolean;
  /** 過去12か月でよく売れた3か月の平均（最盛期） */
  peak?: number | null;
  /** いまの推定月商 = 価格 × 月間販売数（下限の目安） */
  rev: number;
  /** 最盛期の推定月商 */
  peakRev?: number;
  reviews: number | null;
  rating: number | null;
  months: number | null;
  big: boolean;
  amazon: boolean;
  own: boolean;
}
export interface MarketItem {
  catId: string;
  name: string;
  path: string[];
  kind: 'own' | 'compare' | 'found';
  /** 市場の決め方。category = 細かいカテゴリの売れ筋、keyword = 商品名にキーワードを含む商品 */
  by?: 'category' | 'keyword';
  ownNames: string[];
  n: number;
  size: number;
  sizePeak?: number;
  seasonal?: boolean;
  inBand: number;
  over: number;
  big: number;
  amazon: number;
  topBrand: string;
  topShare: number | null;
  brands: number;
  estimated?: number;
  unknown?: number;
  medReviews: number | null;
  medRating: number | null;
  medPrice: number | null;
  newWinners: number;
  ownRev: number;
  /** 狙い目の基準に合わない点。空なら狙い目。古いデータには無い */
  fails?: string[];
  top: MarketProduct[];
}
export interface Markets {
  updatedAt: string;
  band: [number, number];
  rules?: Record<string, number>;
  items: MarketItem[];
}

export interface SetupComp {
  asin: string;
  title: string;
  brand: string;
  manual: boolean;
  auto: boolean;
  pending: boolean;
}
export interface SetupItem {
  parent: string;
  acct: string;
  name: string;
  title: string;
  rep: string;
  nvar: number;
  isNew: boolean;
  source: 'user' | 'auto' | 'none';
  competitors: SetupComp[];
  hasCandidates: boolean;
  /** 取り込み済みの提案の件数。古いデータには無い */
  picks?: number;
  kw: string[];
  terms: string[];
}

export interface Candidate {
  asin: string;
  title: string;
  brand: string;
  image: string | null;
  price: number | null;
  rating: number | null;
  reviews: number | null;
  sold: number | null;
  catPos: number | null;
  searchPos: number | null;
  group: 'rec' | 'big' | 'other';
  why: string;
  auto: boolean;
}
/** 競合・ベンチマークの提案 1 件 */
export interface Pick {
  asin: string;
  title: string;
  brand: string;
  image: string | null;
  price: number | null;
  rating: number | null;
  reviews: number | null;
  sold: number | null;
  why: string;
  auto: boolean;
  /** 商品の情報をまだ取得できていない */
  missing?: boolean;
}
export interface CandidateDoc {
  updatedAt: string;
  kw: string[];
  terms: string[];
  cat: { id: number; name: string } | null;
  pool: number;
  items: Candidate[];
  /** 商品内容を見て選んだ提案。無い商品は、items から自動で絞った候補を表示する */
  picks?: Pick[];
  picksAt?: string;
}

export interface CompSetting {
  on: boolean;
  manual?: boolean;
  at?: string;
}
export interface FamilySetting {
  competitors?: Record<string, CompSetting>;
  kw?: string[];
  terms?: string[];
  regenAt?: string;
  /** 取り込んだ競合・ベンチマークの提案 */
  picks?: { asin: string; why: string }[];
  picksAt?: string;
}

export interface Db {
  overview: Overview | null;
  own: OwnItem[];
  comps: CompItem[];
  cats: CatItem[];
  sales: Sales | null;
  research: Research | null;
  setup: SetupItem[];
  ownAsins: string[];
  families: Record<string, FamilySetting>;
  brands: string[];
  /** 画面で保存したリサーチ条件（まだ取得に反映されていない分を含む） */
  researchSettings: Partial<ResearchParams> | null;
  markets: Markets | null;
}
