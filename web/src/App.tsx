import { useCallback, useEffect, useMemo, useState } from 'react';
import { accountLabels, dateTime } from './lib/format';
import { explain, MOCK, source } from './lib/source';
import type { Db, TabId } from './lib/types';
import Catalog from './tabs/Catalog';
import Category from './tabs/Category';
import Overview from './tabs/Overview';
import Price from './tabs/Price';
import Research from './tabs/Research';
import Sales from './tabs/Sales';
import Setup from './tabs/Setup';
import Stock from './tabs/Stock';

const TABS: [TabId, string, string][] = [
  ['overview', '', '概要'], ['price', '1', '価格・販促'], ['category', '2', 'カテゴリ順位'], ['catalog', '3', '自社カタログ'],
  ['stock', '4', '競合在庫'], ['research', '5', '新商品リサーチ'], ['sales', '6', '販売実績・セール'], ['setup', '', '競合の設定'],
];
const isTab = (v: string): v is TabId => TABS.some(t => t[0] === v);

function Login({ onError, error }: { onError: (m: string) => void; error: string }) {
  const [id, setId] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id.trim() || !pw) return onError('ID とパスワードを入力してください。');
    setBusy(true);
    try { await source.login(id.trim(), pw); onError(''); } catch (err) { onError(explain(err)); setPw(''); }
    setBusy(false);
  };
  return (
    <div className="login">
      <form onSubmit={submit}>
        <div><h1>競合モニター</h1><p className="sub">ID とパスワードを入力してください。</p></div>
        <label className="fld">ID
          <input type="text" value={id} onChange={e => setId(e.target.value)} autoComplete="username" autoCapitalize="off" spellCheck={false} autoFocus disabled={busy} />
        </label>
        <label className="fld">パスワード
          <input type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="current-password" disabled={busy} />
        </label>
        {error && <p className="err" role="alert">{error}</p>}
        <button type="submit" className="btn" disabled={busy}>{busy ? '確認しています…' : 'ログイン'}</button>
      </form>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [db, setDb] = useState<Db | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [acct, setAcct] = useState('all');
  const [tab, setTab] = useState<TabId>(() => { const h = location.hash.replace('#', ''); return isTab(h) ? h : 'overview'; });
  const labels = useMemo(accountLabels, []);
  const label = useCallback((a: string) => labels[a] || a, [labels]);

  useEffect(() => source.watchUser(setUser), []);

  const load = useCallback(async () => {
    setLoading(true);
    try { setDb(await source.loadAll()); setError(''); } catch (e) { setError(explain(e)); setDb(null); }
    setLoading(false);
  }, []);
  useEffect(() => { if (user) load(); else setDb(null); }, [user, load]);

  const go = (t: TabId) => {
    setTab(t);
    try { history.replaceState(null, '', '#' + t); } catch { /* 埋め込み表示などで使えない場合は無視 */ }
    window.scrollTo(0, 0);
  };

  if (user === undefined) return <div className="center">確認しています…</div>;
  if (user === null) return <Login error={error} onError={setError} />;
  if (!db) {
    return (
      <div className="login">
        <form onSubmit={e => { e.preventDefault(); load(); }}>
          <h1>競合モニター</h1>
          {loading ? <p className="sub">読み込んでいます…</p> : <p className="err" role="alert">{error || 'データを読み込めませんでした。'}</p>}
          {!loading && <button type="submit" className="btn">もう一度読み込む</button>}
          {!loading && !MOCK && <button type="button" className="ghost" onClick={() => source.logout()}>別の ID でログイン</button>}
        </form>
      </div>
    );
  }

  const accounts = db.overview?.accounts?.length ? db.overview.accounts : [...new Set(db.own.map(o => o.acct))];
  const props = { db, acct, label };
  return (
    <div className="wrap">
      <header className="head">
        <div className="head-t">
          <div className="head-n"><h1>競合モニター</h1>{MOCK && <span className="demo">模擬データ</span>}</div>
          <p className="sub">{db.overview ? `${dateTime(db.overview.updatedAt)} 取得` : 'まだ取得結果がありません'}</p>
        </div>
        <div className="top-r">
          <div className="filter">
            <span className="filter-l" id="acct-l">アカウント</span>
            <div className="seg" role="group" aria-labelledby="acct-l">
              {['all', ...accounts].map(a => (
                <button key={a} aria-pressed={acct === a} onClick={() => setAcct(a)}>{a === 'all' ? 'すべて' : label(a)}</button>
              ))}
            </div>
          </div>
          <button className="ghost" onClick={load} disabled={loading}>{loading ? '読み込み中…' : '再読み込み'}</button>
          {!MOCK && <button className="ghost" onClick={() => source.logout()}>ログアウト</button>}
        </div>
      </header>
      <div className="tabs-w">
        <div className="tabs" role="tablist" aria-label="機能">
          {TABS.map(([id, no, name]) => (
            <button key={id} role="tab" id={`tab-${id}`} aria-selected={tab === id} onClick={() => go(id)}>
              {no && <span className="no">{no}</span>}{name}
            </button>
          ))}
        </div>
      </div>
      <main className="panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === 'overview' && <Overview db={db} acct={acct} go={go} />}
        {tab === 'price' && <Price {...props} />}
        {tab === 'category' && <Category db={db} acct={acct} />}
        {tab === 'catalog' && <Catalog {...props} />}
        {tab === 'stock' && <Stock {...props} />}
        {tab === 'research' && <Research db={db} />}
        {tab === 'sales' && <Sales {...props} />}
        {tab === 'setup' && <Setup {...props} />}
      </main>
      <p className="foot">金額は税込の表示価格、順位は Amazon.co.jp のランキングです。データは Keepa から取得しています。</p>
    </div>
  );
}
