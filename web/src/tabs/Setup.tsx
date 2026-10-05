import { useEffect, useMemo, useRef, useState } from 'react';
import { matches, Pill, Price, ProductLink, SearchBox, Thumb } from '../components/ui';
import { num, parseAsin, yen } from '../lib/format';
import { explain, source } from '../lib/source';
import type { CandidateDoc, CompSetting, Db, FamilySetting, SetupItem } from '../lib/types';

const GROUP: Record<string, string> = { rec: '自動の候補', big: '大手らしい', other: '別の用途' };
const AUTO_SHORTLIST = 8;      // 提案がまだない商品で、自動の候補から表示する件数
const splitWords = (s: string) => s.split(/[、,]/).map(x => x.trim()).filter(Boolean);

/** 表の 1 行ぶん。提案・自動の候補・手動で追加した商品を同じ形で扱う。 */
interface Row {
  asin: string;
  title: string;
  brand: string;
  image?: string | null;
  price?: number | null;
  rating?: number | null;
  reviews?: number | null;
  sold?: number | null;
  why: string;
  /** 商品名や価格をまだ取得していない */
  pending: boolean;
  tag?: string;
}

/** 「競合: 〜」「ベンチマーク: 〜」の形の理由を、区分と本文に分ける。 */
function Why({ text, tag }: { text: string; tag?: string }) {
  const m = text.match(/^(競合|ベンチマーク)\s*[:：]\s*(.*)$/);
  if (m) return <><Pill kind={m[1] === '競合' ? 'own' : 'good'}>{m[1]}</Pill><div className="cellsub">{m[2]}</div></>;
  if (tag) return <><Pill kind="neutral">{tag}</Pill>{text && <div className="cellsub">{text}</div>}</>;
  return text ? <>{text}</> : <span className="mut">なし</span>;
}

export default function Setup({ db, acct, label }: { db: Db; acct: string; label: (a: string) => string }) {
  const [fam, setFam] = useState<Record<string, FamilySetting>>(db.families);
  const [brands, setBrands] = useState<string[]>(db.brands);
  const [cands, setCands] = useState<Record<string, CandidateDoc | null>>({});
  const accounts = useMemo(() => {
    const have = new Set(db.setup.map(it => it.acct));
    const order = (db.overview?.accounts || []).filter(a => have.has(a));
    return [...order, ...[...have].filter(a => !order.includes(a))];
  }, [db.setup, db.overview]);
  const [tab, setTab] = useState(acct !== 'all' && accounts.includes(acct) ? acct : accounts[0] ?? '');
  /** アカウントごとに、最後に開いていた商品を覚えておく */
  const [selBy, setSelBy] = useState<Record<string, string>>({});
  const listRef = useRef<HTMLUListElement>(null);
  const [q, setQ] = useState('');
  const [onlyUnset, setOnlyUnset] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [asinInput, setAsinInput] = useState('');
  const [msg, setMsg] = useState('');
  const [kwText, setKwText] = useState('');
  const [termText, setTermText] = useState('');
  const [importText, setImportText] = useState('');
  const [importMsg, setImportMsg] = useState('');
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
    if (doc) return (doc.picks?.length ? doc.picks : doc.items).filter(i => i.auto).map(i => i.asin);
    return it.competitors.filter(c => c.auto).map(c => c.asin);
  };
  const pickCount = (it: SetupItem) => fam[it.parent]?.picks?.length ?? it.picks ?? 0;

  const byUser = (it: SetupItem) => !!Object.keys(fam[it.parent]?.competitors || {}).length;

  // 画面上部のアカウント切り替えで 1 つを選んだら、このタブも同じアカウントに合わせる
  useEffect(() => { if (acct !== 'all' && accounts.includes(acct)) setTab(acct); }, [acct, accounts]);

  const all = db.setup.filter(it => it.acct === tab);
  const cur: SetupItem | undefined = all.find(it => it.parent === selBy[tab]) ?? all[0];
  // 並び順は固定。選んだあとに行が動かないよう、開いている商品は絞り込み中も一覧に残す
  const list = all.filter(it => matches(q, it.name, it.title, it.rep, it.parent) && (!onlyUnset || !byUser(it) || it === cur));
  const pos = cur ? all.indexOf(cur) : -1;
  const next = list.find(it => all.indexOf(it) > pos);
  const prev = [...list].reverse().find(it => all.indexOf(it) < pos);
  const chosen = all.filter(byUser).length;
  const total = new Set(all.flatMap(selected)).size;

  /** 商品を切り替える。提案の先頭が画面の上に隠れているときは、そこまで戻す。 */
  const pick = (parent: string) => {
    setSelBy(s => ({ ...s, [tab]: parent }));
    const top = document.getElementById('detail')?.getBoundingClientRect().top;
    if (top != null && top < 48) window.scrollBy({ top: top - 56 });
  };

  // 左の一覧で、開いている商品が見える位置にくるようにする（一覧の中だけを動かす）
  useEffect(() => {
    const box = listRef.current;
    const el = cur && box?.querySelector<HTMLElement>(`[data-p="${cur.parent}"]`);
    if (!box || !el) return;
    const a = el.offsetTop - box.offsetTop, b = a + el.offsetHeight;
    if (a < box.scrollTop) box.scrollTop = a - 4;
    else if (b > box.scrollTop + box.clientHeight) box.scrollTop = b - box.clientHeight + 4;
  }, [cur?.parent, tab]);

  useEffect(() => {
    if (!cur) return;
    setMsg(''); setAsinInput(''); setShowAll(false);
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
    const known = doc?.items.some(i => i.asin === asin) || doc?.picks?.some(i => i.asin === asin);
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

  /** 提案のファイル（{自社の代表ASIN または 親ASIN: [{asin, why}]}）を取り込む。 */
  const importPicks = async (e: React.FormEvent) => {
    e.preventDefault();
    let data: unknown;
    try { data = JSON.parse(importText); } catch { return setImportMsg('内容を読み取れませんでした。提案のファイルの中身を、そのまま貼り付けてください。'); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return setImportMsg('形式が違います。提案のファイルの中身を、そのまま貼り付けてください。');
    const byKey: Record<string, string> = {};
    for (const it of db.setup) { byKey[it.parent] = it.parent; byKey[it.rep] = it.parent; }
    const out: Record<string, { asin: string; why: string }[]> = {};
    let n = 0, unknown = 0;
    for (const [key, rows] of Object.entries(data as Record<string, unknown>)) {
      const parent = byKey[key.trim().toUpperCase()];
      if (!parent || !Array.isArray(rows)) { unknown += 1; continue; }
      const seen = new Set<string>();
      const picks = [];
      for (const r of rows as { asin?: unknown; why?: unknown }[]) {
        const asin = parseAsin(String(r?.asin ?? ''));
        if (!asin || seen.has(asin) || ownAsins.has(asin)) continue;
        seen.add(asin);
        picks.push({ asin, why: String(r?.why ?? '').slice(0, 120) });
      }
      if (picks.length) { out[parent] = picks; n += picks.length; }
    }
    if (!n) return setImportMsg('取り込める提案がありませんでした。');
    setBusy(true);
    try {
      const at = await source.savePicks(out);
      setFam(f => {
        const next = { ...f };
        for (const [parent, picks] of Object.entries(out)) next[parent] = { ...next[parent], picks, picksAt: at };
        return next;
      });
      setImportText('');
      setImportMsg(`${Object.keys(out).length}商品・${n}件の提案を取り込みました。商品名や価格は、次回の取得で入ります。${unknown ? `（一覧にない商品 ${unknown}件は読み飛ばしました）` : ''}`);
    } catch (err) { setImportMsg(explain(err)); }
    setBusy(false);
  };

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setImportText(await file.text());
    setImportMsg('ファイルを読み込みました。「取り込む」を押してください。');
  };

  const nav = cur && (
    <div className="nav">
      <button type="button" className="ghost" disabled={!prev} onClick={() => prev && pick(prev.parent)}>前の商品</button>
      <span className="mut">{pos + 1} / {all.length}</span>
      <button type="button" className="ghost" disabled={!next} onClick={() => next && pick(next.parent)}>次の商品</button>
    </div>
  );
  let detail = <section className="card" id="detail"><p className="empty">このアカウントには、表示する商品がありません</p></section>;
  if (cur) {
    const s = fam[cur.parent];
    const on = new Set(selected(cur));
    const user = s?.competitors || {};
    const lower = brands.map(b => b.toLowerCase());
    const pool = (doc?.items || []).filter(i => !lower.includes(i.brand.toLowerCase()));
    const known = (asin: string) => doc?.picks?.find(p => p.asin === asin && !p.missing) ?? pool.find(i => i.asin === asin);
    const blank = (asin: string, why: string, tag?: string): Row => {
      const k = known(asin);
      return k ? { ...k, why, pending: false, tag }
        : { asin, title: info[asin]?.title || '', brand: info[asin]?.brand || '', why, pending: !info[asin], tag };
    };
    // 提案: 取り込んだものがあればそれを、なければ自動の候補を絞って表示する
    const proposed = !!s?.picks?.length || !!doc?.picks?.length;
    const fresh = doc?.picks && (!s?.picks || doc.picksAt === s.picksAt);
    const picks: Row[] = fresh ? doc!.picks!.map(p => ({ ...p, pending: !!p.missing }))
      : s?.picks?.length ? s.picks.map(p => blank(p.asin, p.why))
      : pool.filter(i => i.group === 'rec').slice(0, AUTO_SHORTLIST).map(i => ({ ...i, why: '', pending: false, tag: '自動の候補' }));
    const shown = new Set(picks.map(p => p.asin));
    const extra: Row[] = Object.keys(user).filter(a => !shown.has(a)).map(a => blank(a, '', user[a]?.manual ? '手動で追加' : '選択中'));
    for (const r of extra) shown.add(r.asin);
    const rest: Row[] = pool.filter(i => !shown.has(i.asin)).map(i => ({ ...i, why: i.why || '', pending: false, tag: GROUP[i.group] || '候補' }));
    const rows = [...extra, ...picks, ...(showAll ? rest : [])];
    const mine = db.own.find(o => o.parent === cur.parent);
    detail = (
      <section className="card" id="detail">
        <div className="card-h">
          <div className="dh">
            <h2>「{cur.name}」の競合</h2>
            <p className="sub"><ProductLink asin={cur.rep}>{cur.rep}</ProductLink>・色やサイズ {cur.nvar}件{mine?.price != null ? `・自社価格 ${yen(mine.price)}` : ''}・
              {s?.competitors && Object.keys(s.competitors).length ? `選択済み ${on.size}件` : `自動で監視中 ${on.size}件`}</p>
          </div>
          {nav}
        </div>
        <p className="sub">
          {proposed
            ? `商品内容を見て選んだ、競合・ベンチマークの提案 ${picks.length}件です。監視する商品を2つほど選んでください。`
            : doc ? `この商品の提案はまだ作っていません。同じカテゴリの売れ筋と検索結果から、自動で ${picks.length}件に絞って表示しています。` : ''}
          {' '}選ぶまでは、上から出品のある2件を自動で監視します。</p>
        {doc === undefined && <p className="empty">候補を読み込んでいます…</p>}
        {doc === null && !rows.length && <p className="empty">この商品の候補はまだ作られていません。次回の取得で作ります。ASIN での追加は今すぐできます。</p>}
        {rows.length > 0 && (
          <div className="tw">
            <table className="tbl">
              <thead><tr><th>監視</th><th>商品</th><th className="n">価格</th><th className="n">評価</th><th className="n">月間販売</th><th className="why">区分と理由</th></tr></thead>
              <tbody>
                {rows.map(c => (
                  <tr key={c.asin}>
                    <td><input type="checkbox" id={`c-${c.asin}`} checked={on.has(c.asin)} disabled={busy}
                      onChange={e => apply(cur, { [c.asin]: { ...user[c.asin], on: e.target.checked } }, e.target.checked ? '監視に加えました。' : '監視から外しました。')} /></td>
                    <td className="name">
                      <div className="prod"><Thumb src={c.image} />
                        <div>
                          <label htmlFor={`c-${c.asin}`}><b>{c.title || `ASIN ${c.asin}`}</b></label>
                          <div className="cellsub">{c.brand ? `${c.brand}・` : ''}<ProductLink asin={c.asin}>{c.asin}</ProductLink>
                            {user[c.asin]?.manual && <>・<button type="button" className="link" disabled={busy} onClick={() => apply(cur, { [c.asin]: null }, `${c.asin} を削除しました。`)}>削除</button></>}
                            {c.brand && !user[c.asin]?.manual && showAll && <>・<button type="button" className="link" disabled={busy} onClick={() => setBrandList([...new Set([...brands, c.brand])], `「${c.brand}」を除外しました。全商品の候補から外れます。`)}>このブランドを除外</button></>}
                          </div>
                          <div className="why-m"><Why text={c.why} tag={c.tag} /></div>
                        </div>
                      </div>
                    </td>
                    {c.pending ? <td className="n" colSpan={3}><span className="mut">次回の取得で反映</span></td> : (
                      <>
                        <td className="n"><Price value={c.price} /></td>
                        <td className="n">{c.rating != null ? c.rating.toFixed(1) : <span className="mut">不明</span>}
                          <div className="cellsub">{c.reviews != null ? `${num(c.reviews)}件` : 'レビュー不明'}</div></td>
                        <td className="n">{c.sold != null ? `${num(c.sold)}点以上` : <span className="mut">表示なし</span>}</td>
                      </>
                    )}
                    <td className="why"><Why text={c.why} tag={c.tag} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rest.length > 0 && (
          <label className="chk"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} />ほかの候補も表示（{rest.length}件。カテゴリの売れ筋と検索結果から自動で集めたもの）</label>
        )}
        <form className="form addform" onSubmit={add}>
          <label className="fld">提案にない競合を追加
            <input type="text" value={asinInput} onChange={e => setAsinInput(e.target.value)} placeholder="ASIN または Amazon の商品 URL" autoComplete="off" />
          </label>
          <button type="submit" className="btn" disabled={busy}>競合に追加</button>
        </form>
        <div className="card-h">
          <p className="sub dh" role="status">{msg || 'チェックを入れた商品を監視します。変更は次回の取得から、ほかのタブに反映されます。'}</p>
          {nav}
        </div>
        <details>
          <summary>自動の候補の出し方を調整する</summary>
          <form className="form kwform" onSubmit={saveKw}>
            <label className="fld">商品名が近いと判定する語（「、」区切り）
              <input type="text" value={kwText} onChange={e => setKwText(e.target.value)} />
            </label>
            <label className="fld">検索語（「、」区切りで3つまで）
              <input type="text" value={termText} onChange={e => setTermText(e.target.value)} />
            </label>
            <button type="submit" className="btn" disabled={busy}>保存して候補を作り直す</button>
          </form>
          <p className="sub">「ほかの候補」と、市場の比較で使う語です。自動で選んだ初期値なので、合わないときに直してください。</p>
        </details>
      </section>
    );
  }

  const state = (it: SetupItem) => {
    const n = selected(it).length;
    return byUser(it) ? { c: 'good', text: `選択済み ${n}件` } : n ? { c: 'neutral', text: `自動で監視 ${n}件` } : { c: 'warn', text: '未設定' };
  };
  const options = cur && !list.includes(cur) ? [cur, ...list] : list;

  return (
    <>
      <section className="card">
        <div>
          <h2>競合の設定</h2>
          <p className="sub">アカウントと自社商品を選ぶと、その商品の競合・ベンチマークの提案（5〜10 件）を表示します。監視する商品にチェックを入れてください。</p>
        </div>
        {accounts.length > 1 && (
          <div className="seg accts" role="group" aria-label="アカウント">
            {accounts.map(a => (
              <button key={a} type="button" aria-pressed={tab === a} onClick={() => setTab(a)}>
                {label(a)}<span className="cnt">{db.setup.filter(it => it.acct === a).length}</span>
              </button>
            ))}
          </div>
        )}
        <p>{label(tab)}の <b>{all.length}</b>商品のうち、競合を選択済み <b>{chosen}</b>、自動で監視中 <b>{all.length - chosen}</b>。監視中の競合は <b>{total}</b>件です。</p>
      </section>
      <div className="setup-grid">
        <section className="card picker" aria-label="自社商品">
          <div className="form">
            <SearchBox value={q} onChange={setQ} />
            <label className="chk"><input type="checkbox" checked={onlyUnset} onChange={e => setOnlyUnset(e.target.checked)} />まだ選んでいない商品だけ</label>
          </div>
          {cur && (
            <label className="fld psel">自社商品（{list.length}件）
              <select value={cur.parent} onChange={e => pick(e.target.value)}>
                {options.map(it => <option key={it.parent} value={it.parent}>{byUser(it) ? '✓ ' : ''}{it.name}</option>)}
              </select>
            </label>
          )}
          <ul className="plist" ref={listRef}>
            {list.map(it => {
              const st = state(it);
              return (
                <li key={it.parent}>
                  <button type="button" className="pitem" data-p={it.parent} title={it.title}
                    aria-current={cur && it.parent === cur.parent ? 'true' : undefined} onClick={() => pick(it.parent)}>
                    <span className="pitem-n">{it.name}</span>
                    <span className="pitem-s"><i className={`dot p-${st.c}`} />{st.text}{it.isNew ? '・新しく追加' : ''}{pickCount(it) ? '' : '・提案なし'}</span>
                  </button>
                </li>
              );
            })}
            {!list.length && <li className="empty">該当する商品はありません</li>}
          </ul>
        </section>
        {detail}
      </div>
      <section className="card">
        <div><h2>除外しているブランド</h2><p className="sub">ここにあるブランドは、自動の候補に出しません。大手ブランドなど、競合として見ないものを登録します。</p></div>
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
      <section className="card">
        <details>
          <summary>提案を取り込む（管理用）</summary>
          <form className="form importform" onSubmit={importPicks}>
            <label className="fld">提案のファイル（JSON）
              <input type="file" accept=".json,application/json,text/plain" onChange={e => readFile(e.target.files?.[0])} />
            </label>
            <label className="fld wide">または中身を貼り付け
              <textarea value={importText} onChange={e => setImportText(e.target.value)} rows={4} spellCheck={false} placeholder='{"自社のASIN": [{"asin": "競合のASIN", "why": "競合: 理由"}]}' />
            </label>
            <button type="submit" className="btn" disabled={busy || !importText.trim()}>取り込む</button>
          </form>
          <p className="sub" role="status">{importMsg || '商品ごとの競合・ベンチマークの提案をまとめて取り込みます。同じ商品の提案は置き換えます。すでに選んだ競合は変わりません。'}</p>
        </details>
      </section>
    </>
  );
}
