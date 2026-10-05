// データの読み書き。本番は Firestore、VITE_MOCK=1 のときは public/mock/db.json を使う。
import { initializeApp } from 'firebase/app';
import { getAuth, onAuthStateChanged, signInWithEmailAndPassword, signOut } from 'firebase/auth';
import { deleteField, doc, getDoc, getFirestore, setDoc } from 'firebase/firestore';
import type { CandidateDoc, CompSetting, Db, FamilySetting, ResearchParams } from './types';

export const MOCK = import.meta.env.VITE_MOCK === '1';

export interface Source {
  /** ログイン状態を監視する。ログイン中なら ID、していなければ null を渡す。 */
  watchUser(cb: (user: string | null) => void): () => void;
  login(id: string, password: string): Promise<void>;
  logout(): Promise<void>;
  loadAll(): Promise<Db>;
  candidates(parent: string): Promise<CandidateDoc | null>;
  /** 競合の選択を保存する。値が null の ASIN は削除する。 */
  saveCompetitors(parent: string, changes: Record<string, CompSetting | null>): Promise<void>;
  saveKeywords(parent: string, kw: string[], terms: string[]): Promise<void>;
  saveBrands(excluded: string[]): Promise<void>;
  saveResearch(params: ResearchParams): Promise<void>;
}

function toDb(get: (path: string) => any): Db {
  return {
    overview: get('views/overview') ?? null,
    own: get('views/own')?.items ?? [],
    comps: get('views/comps')?.items ?? [],
    cats: get('views/cats')?.items ?? [],
    sales: get('views/sales') ?? null,
    research: get('views/research') ?? null,
    setup: get('views/setup')?.items ?? [],
    ownAsins: get('views/setup')?.ownAsins ?? [],
    families: get('settings/families')?.items ?? {},
    brands: get('settings/brands')?.excluded ?? [],
    researchSettings: get('settings/research') ?? null,
    markets: get('views/markets') ?? null,
  };
}

const VIEW_PATHS = ['views/overview', 'views/own', 'views/comps', 'views/cats', 'views/sales', 'views/research', 'views/setup',
  'settings/families', 'settings/brands', 'settings/research', 'views/markets'];

// ---------------------------------------------------------------- 模擬データ
function mockSource(): Source {
  let docs: Record<string, any> | null = null;
  const load = async () => {
    if (!docs) docs = await fetch(`${import.meta.env.BASE_URL}mock/db.json`).then(r => r.json());
    return docs!;
  };
  const family = (d: Record<string, any>, parent: string): FamilySetting => {
    d['settings/families'] ??= { items: {} };
    d['settings/families'].items[parent] ??= {};
    return d['settings/families'].items[parent];
  };
  return {
    watchUser(cb) { cb('demo'); return () => {}; },
    async login() {},
    async logout() {},
    async loadAll() { const d = await load(); return toDb(p => structuredClone(d[p])); },
    async candidates(parent) { const d = await load(); return structuredClone(d[`candidates/${parent}`] ?? null); },
    async saveCompetitors(parent, changes) {
      const f = family(await load(), parent);
      f.competitors ??= {};
      for (const [asin, v] of Object.entries(changes)) {
        if (v === null) delete f.competitors[asin]; else f.competitors[asin] = v;
      }
    },
    async saveKeywords(parent, kw, terms) {
      Object.assign(family(await load(), parent), { kw, terms, regenAt: new Date().toISOString() });
    },
    async saveBrands(excluded) { (await load())['settings/brands'] = { excluded }; },
    async saveResearch(params) { (await load())['settings/research'] = params; },
  };
}

// ---------------------------------------------------------------- Firebase
function firebaseSource(): Source {
  if (!import.meta.env.VITE_FIREBASE_API_KEY || !import.meta.env.VITE_FIREBASE_PROJECT_ID) {
    // ビルド時に Firebase の設定が渡されていない。画面を真っ白にせず、理由を表示する
    const fail = async () => { throw new Error('Firebase の設定がありません。ビルド時の環境変数を確認してください。'); };
    return { watchUser(cb) { cb(null); return () => {}; }, login: fail, logout: async () => {}, loadAll: fail as never, candidates: fail as never,
      saveCompetitors: fail, saveKeywords: fail, saveBrands: fail, saveResearch: fail };
  }
  const app = initializeApp({
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID,
  });
  const auth = getAuth(app);
  const db = getFirestore(app);
  const domain = String(import.meta.env.VITE_LOGIN_DOMAIN || 'example.com');
  const ref = (path: string) => { const [c, d] = path.split('/'); return doc(db, c, d); };
  const read = async (path: string) => { const s = await getDoc(ref(path)); return s.exists() ? s.data() : undefined; };
  return {
    watchUser(cb) { return onAuthStateChanged(auth, u => cb(u ? (u.email || '').split('@')[0] : null)); },
    async login(id, password) {
      const email = id.includes('@') ? id : `${id}@${domain}`;
      await signInWithEmailAndPassword(auth, email, password);
    },
    async logout() { await signOut(auth); },
    async loadAll() {
      const got = await Promise.all(VIEW_PATHS.map(read));
      const map: Record<string, any> = {};
      VIEW_PATHS.forEach((p, i) => { map[p] = got[i]; });
      return toDb(p => map[p]);
    },
    async candidates(parent) { return ((await read(`candidates/${parent}`)) as CandidateDoc | undefined) ?? null; },
    async saveCompetitors(parent, changes) {
      const competitors: Record<string, unknown> = {};
      for (const [asin, v] of Object.entries(changes)) competitors[asin] = v === null ? deleteField() : v;
      await setDoc(ref('settings/families'), { items: { [parent]: { competitors } } }, { merge: true });
    },
    async saveKeywords(parent, kw, terms) {
      await setDoc(ref('settings/families'), { items: { [parent]: { kw, terms, regenAt: new Date().toISOString() } } }, { merge: true });
    },
    async saveBrands(excluded) { await setDoc(ref('settings/brands'), { excluded }); },
    async saveResearch(params) { await setDoc(ref('settings/research'), params); },
  };
}

export const source: Source = MOCK ? mockSource() : firebaseSource();

/** Firebase のエラーを、利用者向けの文にする。 */
export function explain(e: unknown): string {
  const code = (e as { code?: string })?.code || '';
  if (code === 'permission-denied') return 'この ID には閲覧の許可がありません。管理者に名簿への登録を依頼してください。';
  if (['auth/invalid-credential', 'auth/wrong-password', 'auth/user-not-found', 'auth/invalid-email'].includes(code)) return 'ID またはパスワードが違います。';
  if (code === 'auth/too-many-requests') return '失敗が続いたため一時的にロックされています。しばらく待ってからやり直してください。';
  if (code === 'auth/network-request-failed' || code === 'unavailable') return 'ネットワークに接続できません。';
  return '処理に失敗しました（' + (code || (e as Error)?.message || '不明なエラー') + '）';
}
