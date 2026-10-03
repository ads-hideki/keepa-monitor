import { useState } from 'react';
import { Pill, SEV_LABEL } from '../components/ui';
import { dateTime, hoursSince, num } from '../lib/format';
import type { Db, TabId } from '../lib/types';

const TAB_NAME: Record<TabId, string> = {
  overview: '概要', price: '価格・販促', category: 'カテゴリ順位', catalog: '自社カタログ',
  stock: '競合在庫', research: '新商品リサーチ', sales: '販売実績・セール', setup: '競合の設定',
};
const TILES: [TabId, string, string][] = [
  ['price', '競合の値下げ', 'drop'], ['price', 'クーポン・セール開始', 'promo'], ['stock', '競合の在庫切れ', 'stock'],
  ['catalog', '自社商品の異常', 'catalog'], ['category', 'カテゴリ新規参入', 'entrant'],
];
const LIMIT = 12;

export default function Overview({ db, acct, go }: { db: Db; acct: string; go: (t: TabId) => void }) {
  const [all, setAll] = useState(false);
  const ov = db.overview;
  if (!ov) return <section className="card"><p className="empty">まだ取得結果がありません。最初の取得が終わると表示されます。</p></section>;
  const alerts = ov.alerts.filter(a => acct === 'all' || !a.acct || a.acct === acct);
  const count = (t: string) => alerts.filter(a => a.type === t).length;
  const shown = all ? alerts : alerts.slice(0, LIMIT);
  const cap = (ov.tokens.rate || 25) * 60 * 24;
  const today = ov.tokens.today || 0;
  const stale = hoursSince(ov.updatedAt);
  return (
    <>
      {stale != null && stale > 30 && (
        <p className="banner">最後の取得から {Math.floor(stale)} 時間たっています。自動実行が止まっていないか確認してください。</p>
      )}
      {ov.warnings.map(w => <p className="banner" key={w}>{w}</p>)}
      <div className="tiles">
        {TILES.map(([tab, label, type]) => (
          <button className="tile" key={type} onClick={() => go(tab)}>
            <span className="tile-l">{label}</span>
            <span className="tile-v">{count(type)}<small>件</small></span>
          </button>
        ))}
      </div>
      <div className="cols">
        <section className="card grow">
          <div>
            <h2>通知</h2>
            <p className="sub">{dateTime(ov.updatedAt)} 時点。重要度の高い順に並べています。全 {alerts.length}件。</p>
          </div>
          <ul className="alerts">
            {shown.map((a, i) => (
              <li key={i}>
                <div className="al-p"><Pill kind={a.sev}>{SEV_LABEL[a.sev]}</Pill></div>
                <div className="al-b">
                  <div className="al-t">{a.text}</div>
                  {a.sub && <div className="al-s">{a.sub}</div>}
                </div>
                <button className="link" onClick={() => go(a.tab)}>{TAB_NAME[a.tab]}を見る</button>
              </li>
            ))}
            {!alerts.length && <li className="empty">通知はありません</li>}
          </ul>
          {alerts.length > LIMIT && (
            <button className="link more" onClick={() => setAll(v => !v)}>{all ? `上位${LIMIT}件だけ表示` : `残り ${alerts.length - LIMIT}件を表示`}</button>
          )}
        </section>
        <div className="side">
          <section className="card">
            <div><h2>監視対象</h2><p className="sub">在庫または入荷予定のある自社商品です。全アカウントの合計。</p></div>
            <div className="kv">
              <div><span>自社商品</span><b>{num(ov.monitor.families)} 商品</b></div>
              <div><span>色・サイズを含む ASIN</span><b>{num(ov.monitor.asins)} 件</b></div>
              <div><span>監視中の競合</span><b>{num(ov.monitor.competitors)} 件</b></div>
              <div><span>競合が未設定の商品</span><b>{num(ov.monitor.unset)} 商品</b></div>
            </div>
          </section>
          <section className="card">
            <div><h2>API トークンの消費</h2><p className="sub">今日の合計です。1日に使える量は {num(cap)} です。</p></div>
            <div className="big">{num(today)} <small>/ {num(cap)} トークン</small></div>
            <div className="meter" role="img" aria-label={`1日の上限の${Math.round((today / cap) * 100)}%を使用`}>
              <i style={{ width: `${Math.min(100, (today / cap) * 100).toFixed(1)}%` }} />
            </div>
            <p className="sub">直前の取得（{ov.job}）の内訳</p>
            <div className="kv">
              {Object.entries(ov.tokens.byLabel).map(([k, v]) => <div key={k}><span>{k}</span><b>{num(v)}</b></div>)}
              {!Object.keys(ov.tokens.byLabel).length && <div><span className="mut">消費なし</span><b>0</b></div>}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
