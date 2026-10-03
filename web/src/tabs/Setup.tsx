import { useEffect, useMemo, useState } from 'react';
import { matches, Pill, Price, ProductLink, SearchBox, Thumb } from '../components/ui';
import { num, parseAsin, yen } from '../lib/format';
import { explain, source } from '../lib/source';
import type { CandidateDoc, CompSetting, Db, FamilySetting, SetupItem } from '../lib/types';

const GROUP: Record<string, [string, 'good' | 'neutral'] | null> = { rec: ['推奨', 'good'], big: ['大手らしい', 'neutral'], other: null };
const splitWords = (s: string) => s.split(/[、,]/).map(x => x.trim()).filter(Boolean);

export default function Setup({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [fam, setFam] = useState<Record<string, FamilySetting>>(db.families);
  const [brands, setBrands] = useState<string[]>(db.brands);
  const [cands, setCands] = useState<Record<string, CandidateDoc | null>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [onlyUnset, setOnlyUnset] = useState(false);
  const [asinInput, setAsinInput] = useState('');
  const [msg, setMsg] = useState('');
  const [kwText, setKwText] = useState('');
  const [termText, setTermText] = useState('');
  const [busy, setBusy] = useState(false);

  const ownAsins = useMemo(() => new Set(db.ownAsins), [db.ownAsins]);
  const info = useMemo(() => {
    const m: Record<string, { title: string; brand: string }> = {};
    for (const c of db.comps) if (c.title) m[c.asin] = { title: c.title, brand: c.brand };
    return m;
  }, [db.comps]);

  /** いま監視対象になっている競合の ASIN。利用者が選んでいればその選択、なければ自動選択。 */
  const selected = (it: SetupItem): string[] => {
    const user = fam[it.parent]?.competitors;
    if (user && Object.keys(user).length) return Object.keys(user).filter(a => user[a].on);
    const doc = cands[it.parent];
    if (doc) return doc.items.filter(i => i.auto).map(i => i.asin);
    return it.competitors.filter(c => c.auto).map(c => c.asin);
  };

  const all = db.setup.filter(it => acct === 'all' || it.acct === acct);
  const list = all
    .filter(it => matches(q, it.name, it.title, it.rep, it.parent) && (!onlyUnset || !selected(it).length))
    .sort((a, b) => (selected(a).length ? 1 : 0) - (selected(b).length ? 1 : 0));
  const cur = list.find(it => it.parent === sel) ?? list[0];
  const unset = all.filter(it => !selected(it).length).length;
  const total = new Set(all.flatMap(selected)).size;

  useEffect(() => {
    if (!cur) return;
    setMsg(''); setAsinInput('');
    if (cands[cur.parent] === undefined) {
      source.candidates(cur.parent).then(d => setCands(c => ({ ...c, [cur.parent]: d }))).catch(e => setMsg(explain(e)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur?.parent]);

  const doc = cur ? cands[cur.parent] : undefined;
  useEffect(() => {
    if (!cur) return;
    const s = fam[cur.parent];
    setKwText((s?.kw?.length ? s.kw : doc?.kw ?? cur.kw).join('、'));
    setTermText((s?.terms?.length ? s.terms : doc?.terms ?? cur.terms).join('、'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur?.parent, doc]);

  /** 競合の選択を保存する。まだ何も選んでいない商品は、自動選択を利用者の選択として書き写してから変える。 */
  const apply = async (it: SetupItem, changes: Record<string, CompSetting | null>, done: string) => {
    const user = fam[it.parent]?.competitors;
    const full: Record<string, CompSetting | null> = {};
    if (!user || !Object.keys(user).length) for (const a of selected(it)) full[a] = { on: true };
    Object.assign(full, changes);
    setBusy(true);
    try {
      await source.saveCompetitors(it.parent, full);
      setFam(f => {
        const next = { ...(f[it.parent]?.competitors || {}) };
        for (const [a, v] of Object.entries(full)) { if (v === null) delete next[a]; else next[a] = v; }
        return { ...f, [it.parent]: { ...f[it.parent], competitors: next } };
      });
      setMsg(done);
    } catch (e) { setMsg(explain(e)); }
    setBusy(false);
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cur) return;
    const asin = parseAsin(asinInput);
    if (!asin) return setMsg('ASIN を読み取れませんでした。10文字の英数字か、商品ページの URL を入れてください。');
    if (ownAsins.has(asin)) return setMsg(`${asin} は自社商品の ASIN です。競合には追加できません。`);
    if (selected(cur).includes(asin)) return setMsg(`${asin} はすでに監視中です。`);
    const known = doc?.items.some(i => i.asin === asin);
    await apply(cur, { [asin]: { on: true, manual: !known, at: new Date().toISOString() } },
      `${asin} を追加しました。${known ? '' : '商品名や価格は次回の取得で入ります。'}`);
    setAsinInput('');
  };

  const saveKw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cur) return;
    const kw = splitWords(kwText), terms = splitWords(termText);
    if (!kw.length || !terms.length) return setMsg('キーワードと検索語を1つ以上入れてください。');
    setBusy(true);
    try {
      await source.saveKeywords(cur.parent, kw, terms);
      setFam(f => ({ ...f, [cur.parent]: { ...f[cur.parent], kw, terms, regenAt: new Date().toISOString() } }));
      setMsg('保存しました。次回の取得で、この商品の候補を作り直します。');
    } catch (err) { setMsg(explain(err)); }
    setBusy(false);
  };

  const setBrandList = async (next: string[], done: string) => {
    setBusy(true);
    try { await source.saveBrands(next); setBrands(next); setMsg(done); } catch (e) { setMsg(explain(e)); }
    setBusy(false);
  };

  let detail = <section className="card"><p className="empty">表示する商品がありません</p></section>;
  if (cur) {
    const on = new Set(selected(cur));
    const user = fam[cur.parent]?.competitors || {};
    const lower = brands.map(b => b.toLowerCase());
    const items = (doc?.items || []).filter(i => !lower.includes(i.brand.toLowerCase()));
    const extra = Object.keys(user).filter(a => !items.some(i => i.asin === a));       // 候補にない（手動で追加した）ASIN
    const mine = db.own.find(o => o.parent === cur.parent);
    detail = (
      <section className="card" id="detail">
        <div>
          <h2>「{cur.name}」の競合</h2>
          <p className="sub">{label(cur.acct)}・{cur.rep}・色やサイズ {cur.nvar}件{mine?.price != null ? `・自社価格 ${yen(mine.price)}` : ''}。
            {doc ? ` カテゴリ「${doc.cat?.name ?? '不明'}」の上位と検索結果の ${doc.pool}商品から候補を作りました。` : ''}</p>
        </div>
        {doc === undefined && <p className="empty">候補を読み込んでいます…</p>}
        {doc === null && <p className="empty">この商品の候補はまだ作られていません。次回の取得で作ります。ASIN での追加は今すぐできます。</p>}
        {(items.length > 0 || extra.length > 0) && (
          <div className="tw">
            <table className="tbl">
              <thead><tr><th>監視</th><th>区分</th><th>商品</th><th className="n">カテゴリ順位</th><th className="n">価格</th><th className="n">評価</th><th className="n">レビュー数</th><th className="n">月間販売</th><th>判定の理由</th></tr></thead>
              <tbody>
                {extra.map(a => (
                  <tr key={a}>
                    <td><input type="checkbox" id={`c-${a}`} checked={on.has(a)} disabled={busy} onChange={e => apply(cur, { [a]: { ...user[a], on: e.target.checked } }, e.target.checked ? '監視に加えました。' : '監視から外しました。')} /></td>
                    <td>{user[a]?.manual ? <Pill kind="own">手動で追加</Pill> : <Pill kind="neutral">候補外</Pill>}</td>
                    <td className="name">
                      <label htmlFor={`c-${a}`}><b>{info[a]?.title || `ASIN ${a}`}</b></label>
                      <div className="cellsub">{info[a]?.brand ? `${info[a].brand}・` : ''}<ProductLink asin={a}>{a}</ProductLink>・<button type="button" className="link" disabled={busy} onClick={() => apply(cur, { [a]: null }, `${a} を削除しました。`)}>削除</button></div>
                    </td>
                    <td className="n" colSpan={6}><span className="mut">{info[a] ? '価格などは「価格・販促」タブで確認できます' : '次回の取得で反映'}</span></td>
                  </tr>
                ))}
                {items.map(c => {
                  const g = GROUP[c.group];
                  return (
                    <tr key={c.asin}>
                      <td><input type="checkbox" id={`c-${c.asin}`} checked={on.has(c.asin)} disabled={busy} onChange={e => apply(cur, { [c.asin]: { on: e.target.checked } }, e.target.checked ? '監視に加えました。' : '監視から外しました。')} /></td>
                      <td>{g ? <Pill kind={g[1]}>{g[0]}</Pill> : <span className="mut">別の用途</span>}</td>
                      <td className="name">
                        <div className="prod"><Thumb src={c.image} />
                          <div>
                            <label htmlFor={`c-${c.asin}`}><b>{c.title}</b></label>
                            <div className="cellsub">{c.brand || 'ブランド不明'}・<ProductLink asin={c.asin}>{c.asin}</ProductLink>
                              {c.brand && <>・<button type="button" className="link" disabled={busy} onClick={() => setBrandList([...new Set([...brands, c.brand])], `「${c.brand}」を除外しました。全商品の候補から外れます。`)}>このブランドを除外</button></>}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="n">{c.catPos != null ? `${c.catPos}位` : <span className="mut">41位以下</span>}</td>
                      <td className="n"><Price value={c.price} /></td>
                      <td className="n">{c.rating != null ? c.rating.toFixed(1) : <span className="mut">不明</span>}</td>
                      <td className="n">{c.reviews != null ? `${num(c.reviews)}件` : <span className="mut">不明</span>}</td>
                      <td className="n">{c.sold != null ? `${num(c.sold)}点以上` : <span className="mut">不明</span>}</td>
                      <td>{c.why || <span className="mut">なし</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <form className="form addform" onSubmit={add}>
          <label className="fld">候補にない競合を追加
            <input type="text" value={asinInput} onChange={e => setAsinInput(e.target.value)} placeholder="ASIN または Amazon の商品 URL" autoComplete="off" />
          </label>
          <button type="submit" className="btn" disabled={busy}>競合に追加</button>
        </form>
        <p className="sub" role="status">{msg || 'チェックを入れた商品を監視します。変更は次回の取得から、ほかのタブに反映されます。'}</p>
        <details>
          <summary>候補の出し方を調整する</summary>
          <form className="form kwform" onSubmit={saveKw}>
            <label className="fld">商品名が近いと判定する語（「、」区切り）
              <input type="text" value={kwText} onChange={e => setKwText(e.target.value)} />
            </label>
            <label className="fld">検索語（「、」区切りで3つまで）
              <input type="text" value={termText} onChange={e => setTermText(e.target.value)} />
            </label>
            <button type="submit" className="btn" disabled={busy}>保存して候補を作り直す</button>
          </form>
          <p className="sub">語は自動で選んだ初期値です。候補が合わないときに直してください。</p>
        </details>
      </section>
    );
  }

  return (
    <>
      <section className="card">
        <div>
          <h2>競合の設定</h2>
          <p className="sub">自社商品が追加されると、同じカテゴリの売れ筋と検索結果から競合の候補を作ります。選ぶまでは、推奨の上位2件を自動で監視します。</p>
        </div>
        <p>自社 <b>{all.length}</b>商品のうち、競合あり <b>{all.length - unset}</b>、未設定 <b>{unset}</b>。監視中の競合は <b>{total}</b>件です。</p>
      </section>
      {detail}
      <section className="card">
        <div className="card-h">
          <div><h2>自社商品の一覧</h2><p className="sub">商品名を押すと、上に候補を表示します。</p></div>
          <div className="form">
            <SearchBox value={q} onChange={setQ} />
            <label className="chk"><input type="checkbox" checked={onlyUnset} onChange={e => setOnlyUnset(e.target.checked)} />未設定の商品だけ</label>
          </div>
        </div>
        <div className="tw">
          <table className="tbl">
            <thead><tr><th>自社商品</th><th>状態</th><th>監視中の競合</th></tr></thead>
            <tbody>
              {list.map(it => {
                const on = selected(it);
                const byUser = !!Object.keys(fam[it.parent]?.competitors || {}).length;
                return (
                  <tr key={it.parent} className={cur && it.parent === cur.parent ? 'sel' : ''}>
                    <td className="name" title={it.title}>
                      <button className="rowbtn" aria-pressed={cur ? it.parent === cur.parent : false}
                        onClick={() => { setSel(it.parent); document.getElementById('detail')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }}>{it.name}</button>
                      <div className="cellsub">{label(it.acct)}・{it.rep}・色やサイズ {it.nvar}件{it.isNew ? '・新しく追加' : ''}</div>
                    </td>
                    <td>{!on.length ? <Pill kind="warn">未設定</Pill> : byUser ? <Pill kind="good">選択済み {on.length}件</Pill> : <Pill kind="neutral">自動選択 {on.length}件</Pill>}</td>
                    <td>{on.length ? on.map(a => info[a]?.title || a).join('、') : <span className="mut">なし</span>}</td>
                  </tr>
                );
              })}
              {!list.length && <tr><td colSpan={3} className="empty">該当する商品はありません</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div><h2>除外しているブランド</h2><p className="sub">ここにあるブランドは、全商品の候補に出しません。大手ブランドなど、競合として見ないものを登録します。</p></div>
        {brands.length ? (
          <div className="pills">
            {brands.map(b => (
              <span className="pill p-neutral" key={b}>{b}
                <button type="button" className="link x" disabled={busy} aria-label={`${b} の除外をやめる`} onClick={() => setBrandList(brands.filter(x => x !== b), `「${b}」の除外をやめました。`)}>解除</button>
              </span>
            ))}
          </div>
        ) : <p className="empty">除外しているブランドはありません</p>}
      </section>
    </>
  );
}
