// Batch composer: products x template versions -> independently editable outputs, reviewed before anything is generated.
// Copy precedence: template defaults -> batch defaults -> product overrides -> pair overrides -> what you type per output.
// Every change goes through one serial write queue: Generate (and previews, AI drafting) first wait until the server has
// acknowledged everything typed or chosen, so the frozen snapshot is exactly what was reviewed.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, CREATIVE_TEXT, MODES, type Matrix, type Pair, type Product, type ResolvedSlot, type Template } from "../api";
import { useComposer } from "../components/Composer";
import { Dev, errText, JobLine, newKey, postPaid, readLocal, StatusDot, useJob, useLocal, useToast } from "../lib";
import { NotReplayable, WriteQueue, type WriteOpts } from "../writes";

// Answers to a submission that say nothing was created with its key (anything else, e.g. a sign-in or proxy error,
// says nothing about an earlier attempt, so the key is kept and the next Generate retries the same submission)
const SUBMIT_ANSWERED = ["submission_changed", "preflight_failed", "nothing_to_generate", "missing_idempotency_key", "not_found"];

export default function Generate() {
  const [params, setParams] = useSearchParams();
  const c = useComposer();
  const bid = params.get("batch") || c.batchId;
  useEffect(() => { if (bid && !params.get("batch")) setParams({ batch: bid }, { replace: true }); }, [bid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!bid) return <BatchList onOpen={(id) => { c.setBatchId(id); setParams({ batch: id }); }} />;
  return <BatchComposer key={bid} bid={bid} />; // one batch, one write queue and one submission identity
}

function BatchComposer({ bid }: { bid: string }) {
  const [m, setM] = useState<Matrix | null>(null);
  const mRef = useRef<Matrix | null>(null);
  const [err, setErr] = useState("");
  const [products, setProducts] = useState<Record<string, Product>>({});
  const [templates, setTemplates] = useState<Record<string, Template>>({});
  const [fonts, setFonts] = useState<any[]>([]);
  const [selRows, setSelRows] = useState<string[]>([]);
  const [draftJob, setDraftJob] = useState<string | null>(null);
  // the identity of the submission in progress: kept until its outcome is known, so a retry can never create a second run
  const [submitKey, setSubmitKey] = useLocal<string | null>(`dna.submit.${bid}`, null);
  const [recovered, setRecovered] = useState<{ run_id: string; changed?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const toast = useToast();
  const reload = useRef<() => void>(() => {});
  // a failed choice or action is shown as it is on the server (reloaded), never replayed unseen; typed text is kept and retried
  const q = useMemo(() => new WriteQueue((key, e, o) => {
    if (key.startsWith("load")) return;
    toast(`Not saved: ${errText(e)}`, true);
    if (o.once && !o.read) reload.current();
  }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [, bump] = useState(0);
  useEffect(() => q.subscribe(() => bump((x) => x + 1)), [q]);
  const setMatrix = (x: Matrix) => { mRef.current = x; setM(x); };
  const load = () => q.run("load", () => api.get<Matrix>(`/api/batches/${bid}`).then((x) => { setMatrix(x); setErr(""); }), undefined, { read: true });
  reload.current = () => { void load(); };
  useEffect(() => {
    api.get<Matrix>(`/api/batches/${bid}`).then((x) => { setMatrix(x); setErr(""); }).catch((e) => setErr(errText(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.get<Product[]>("/api/products").then((ps) => setProducts(Object.fromEntries(ps.map((p) => [p.id, p])))).catch(() => {});
    api.get<{ templates: Template[] }>("/api/templates").then((r) => setTemplates(Object.fromEntries(r.templates.map((t) => [t.id, t])))).catch(() => {});
    api.get<any[]>("/api/fonts").then(setFonts).catch(() => {});
  }, []);
  // a submission whose response was lost: ask the server what happened before anything else is sent
  useEffect(() => {
    if (!submitKey) return;
    api.get<{ run_id: string }>(`/api/submissions/${encodeURIComponent(submitKey)}`)
      .then((r) => { setRecovered({ run_id: r.run_id }); setSubmitKey(null); })
      .catch(() => { /* not received (404) or unreachable: the key is kept, so Generate retries the same submission */ });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // unsaved edits: send them when the page goes away, and warn before the browser drops them
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (q.busy || q.failures.length) { q.fireAll(); e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => { window.removeEventListener("beforeunload", warn); q.fireAll(); };
  }, [q]);
  // leaving this page inside the app (a link, Back or Forward): save first; if something cannot be saved, ask
  const blocker = useBlocker(({ currentLocation: a, nextLocation: b }) => (q.busy || q.failures.length > 0) && a.pathname + a.search !== b.pathname + b.search);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    q.flush().then(() => blocker.proceed?.(), () => {
      if (window.confirm("Some changes could not be saved. Copy you typed is kept in this browser and sent again when you come back; other changes would be lost. Leave anyway?")) blocker.proceed?.();
      else blocker.reset?.();
    });
  }, [blocker.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const dj = useJob(draftJob, (j) => { load(); toast(j.status === "completed" ? `${j.result?.drafts ?? 0} AI draft(s) ready to review` : "AI drafting did not complete", j.status !== "completed"); });
  const pairs = m?.pairs || [];
  const roles = useMemo(() => Array.from(new Set(pairs.flatMap((p) => (p.slots || []).map((s) => s.role)))), [pairs]);

  if (err) return <div className="notice bad" role="alert">{err} <Link to="/templates">Back to the library</Link></div>;
  if (!m) return <p className="muted">Loading the batch…</p>;
  const b = m.batch;
  // every write reads the latest acknowledged revision when it is sent (writes are serial, so it is current)
  // a choice made with a control that shows the server's value (`once`) is not retried later; typed fields are
  const patchBatch = (key: string, changes: any, opts: WriteOpts = {}) => q.run(`batch:${key}`, async () => {
    try { setMatrix(await api.patch<Matrix>(`/api/batches/${b.id}`, { base_revision: mRef.current!.batch.revision, changes })); }
    catch (e) {
      if (e instanceof ApiError && e.code === "stale_batch") throw new NotReplayable(`${e.message} (the batch changed elsewhere and was reloaded: check it and redo this change)`);
      throw e;
    }
  }, undefined, opts);
  const setPair = (pid: string, key: string, body: any, opts: WriteOpts = {}) => q.run(`pair:${pid}:${key}`, async () => {
    setMatrix(await api.patch<Matrix>(`/api/batches/${b.id}/pairs/${pid}`, body));
  }, undefined, opts);
  const flushOrSay = async (what: string) => {
    try { await q.flush(); return true; }
    catch (e) { toast(`${what} stopped: some changes were not saved (${(e as Error).message}). Try again when the connection is back. Copy typed into outputs is also kept in this browser; other fields are not, so keep this page open.`, true); return false; }
  };
  const submit = async () => {
    setBusy(true);
    try {
      if (!(await flushOrSay("Generating"))) return;
      const cur = mRef.current!;
      if (cur.counts.blocked > 0) { toast("Some outputs need attention before generating", true); return; }
      const imageryOnly = cur.pairs.filter((p) => p.included && p.mode === "creative" && p.creative_text === "none");
      if (imageryOnly.length && !window.confirm(`${imageryOnly.length} creative output(s) are imagery only: their copy will not appear in the image and no text is requested. Generate anyway?`)) return;
      const key = readLocal<string | null>(`dna.submit.${bid}`, null) || submitKey || newKey(); // shared with other tabs of this batch
      setSubmitKey(key); // stored before sending: if the response is lost, the same key retries the same submission
      try {
        const r = await api.post<any>(`/api/batches/${b.id}/submit`, { idempotency_key: key, name: cur.batch.name });
        if (typeof r?.run_id !== "string") throw new Error("unexpected answer"); // e.g. a login portal's page: not the server's answer
        setSubmitKey(null);
        toast(r.duplicate ? "That submission was already received — opening its run" : `Submitted ${r.outputs} output(s)`);
        nav(`/runs/${r.run_id}`);
      } catch (e) {
        if (e instanceof ApiError && SUBMIT_ANSWERED.includes(e.code)) {
          setSubmitKey(null); // the server answered this submission: nothing (new) was created with this key
          if (e.code === "submission_changed") setRecovered({ run_id: String((e.detail as any).run_id), changed: true });
          toast(errText(e), true);
          void load();
        } else {
          toast("The submission could not be confirmed (connection lost). Generate again to retry it: it cannot create a second run.", true);
        }
      }
    } finally { setBusy(false); }
  };
  const included = pairs.filter((p) => p.included);
  const imageryOnly = included.filter((p) => p.mode === "creative" && p.creative_text === "none").length;
  const saving = q.busy;
  const unsaved = q.failures.length;
  const genLabel = busy ? (saving ? "Saving changes…" : "Submitting…") : `Generate ${included.length} output${included.length === 1 ? "" : "s"}`;
  const anyCreative = (b.defaults.mode || "adapt") === "creative" || pairs.some((p) => p.mode === "creative");
  return (
    <>
      <div className="page-head">
        <div>
          <span className="label">Generate · content review</span>
          <h1 style={{ margin: 0 }}>
            <input aria-label="Batch name" className="h1-input" defaultValue={b.name} onBlur={(e) => e.target.value !== b.name && patchBatch("name", { name: e.target.value })}
                   style={{ font: "600 30px var(--serif)", border: 0, background: "transparent", padding: 0, width: "100%" }} />
          </h1>
          <p className="lede">{m.counts.proposed} proposed · <strong>{m.counts.included} included</strong> · {m.counts.excluded} excluded{m.counts.blocked ? <> · <span style={{ color: "var(--crimson)" }}>{m.counts.blocked} need attention</span></> : null}
            {" "}<span className="small muted" role="status">{unsaved ? `· ${unsaved} change(s) not saved` : saving ? "· saving…" : "· all changes saved"}</span></p>
        </div>
        <div className="row">
          <Link className="btn secondary" to="/templates">Change selection</Link>
          <button className="btn accent" onClick={submit} disabled={busy || !included.length || m.counts.blocked > 0}>{genLabel}</button>
        </div>
      </div>
      {recovered && (
        <div className="notice warn" role="status" style={{ marginBottom: 16 }}>
          {recovered.changed ? "An earlier submission from this page was received as a run before your latest edits. " : "Your last submission was received. "}
          <Link to={`/runs/${recovered.run_id}`}>Open that run</Link>{recovered.changed ? " — or generate again to submit the current content as a new run." : "."}
        </div>
      )}
      {submitKey && !busy && (
        <div className="notice warn small" role="status" style={{ marginBottom: 16 }}>
          A submission from this page was not confirmed. Generate retries that same submission: it cannot create a second run.
        </div>
      )}

      <div className="grid2" style={{ marginBottom: 22 }}>
        <section className="card">
          <h3>Batch defaults <span className="muted small">apply to every output unless a later layer sets a value</span></h3>
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="seg" role="group" aria-label="Default mode">{Object.entries(MODES).map(([k, l]) => (
              <button key={k} aria-pressed={(b.defaults.mode || "adapt") === k} onClick={() => patchBatch("defaults.mode", { defaults: { mode: k } }, { once: true })}>{l}</button>))}</div>
          </div>
          {anyCreative && (
            <div className="row" style={{ marginBottom: 12 }}>
              <div className="seg" role="group" aria-label="Text in creative artwork">{Object.entries(CREATIVE_TEXT).map(([k, l]) => (
                <button key={k} aria-pressed={(b.defaults.creative_text || "overlay") === k} onClick={() => patchBatch("defaults.creative_text", { defaults: { creative_text: k } }, { once: true })}>{l}</button>))}</div>
            </div>
          )}
          {b.defaults.mode !== "adapt" && !m.providers.image_generation && <div className="notice warn small" style={{ marginBottom: 10 }}>No image provider is configured: creative modes are blocked. <Link to="/settings">Settings</Link></div>}
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="seg" role="group" aria-label="Default language">
              <button aria-pressed={(b.defaults.language || "en") === "en"} onClick={() => patchBatch("defaults.language", { defaults: { language: "en" } }, { once: true })}>English</button>
              <button aria-pressed={b.defaults.language === "ar"} onClick={() => patchBatch("defaults.language", { defaults: { language: "ar" } }, { once: true })}>العربية Arabic</button>
            </div>
            {(b.defaults.language === "ar" || pairs.some((p) => p.pair_language === "ar")) && (
              <select aria-label="Arabic font" value={b.defaults.arabic_font || ""} onChange={(e) => patchBatch("defaults.arabic_font", { defaults: { arabic_font: e.target.value || null } }, { once: true })}>
                <option value="">Choose an Arabic-capable font…</option>
                {fonts.map((f) => <option key={f.sha256} value={f.sha256}>{f.names.full}</option>)}
              </select>
            )}
          </div>
          {roles.map((r) => <DefaultCopy key={r} role={r} value={b.defaults.copy?.[r]} onSave={(v) => patchBatch(`defaults.copy.${r}`, { defaults: { copy: { [r]: v } } })} />)}
          <label className="field"><span className="label">Instructions for every output</span>
            <textarea rows={2} defaultValue={b.defaults.instructions || ""} onBlur={(e) => e.target.value !== (b.defaults.instructions || "") && patchBatch("defaults.instructions", { defaults: { instructions: e.target.value } })} /></label>
        </section>
        <section className="card">
          <h3>Apply to a group</h3>
          <BulkApply m={m} roles={roles} products={products} templates={templates} selected={selRows} q={q} onDone={setMatrix} />
          <hr className="rule" />
          <h4>Draft copy with AI</h4>
          <p className="small muted">Claude drafts copy for the selected outputs (or all included). Drafts appear beside each field; nothing you typed is replaced, and a draft is unapproved until you review it.</p>
          <button className="btn secondary small" disabled={!m.providers.copy}
                  onClick={async () => { if (!(await flushOrSay("Drafting"))) return; try { const j = await postPaid<any>(`/api/batches/${b.id}/draft-copy`, { pair_ids: selRows.length ? selRows : included.map((p) => p.pair_id) }); if (j) setDraftJob(j.id); } catch (e) { toast(errText(e), true); } }}>
            Draft copy for {selRows.length || included.length} output(s)</button>
          {!m.providers.copy && <span className="small muted"> — needs a Claude key (<Link to="/settings">Settings</Link>)</span>}
          {m.providers.copy?.mock && <span className="tag bad" style={{ marginLeft: 8 }}>mock</span>}
          {dj && <div style={{ marginTop: 8 }}><JobLine job={dj} label="AI drafting" /></div>}
        </section>
      </div>

      {m.detached.length > 0 && <p className="small muted">{m.detached.length} output(s) left the selection; their content is kept and returns if you re-add the product or template.</p>}
      {pairs.length === 0 && <div className="empty"><h2>No pairings</h2><p className="muted">Select at least one template and one product.</p></div>}
      <div className="stack" style={{ gap: 16 }}>
        {pairs.map((p) => (
          <OutputEditor key={p.pair_id} p={p} batchId={b.id} product={products[p.product_id]} template={templates[p.template_id]} selected={selRows.includes(p.pair_id)}
                        onSelect={(on) => setSelRows((x) => on ? [...x, p.pair_id] : x.filter((y) => y !== p.pair_id))} setPair={setPair} q={q}
                        reload={load} onMatrix={setMatrix} flushOrSay={flushOrSay} />
        ))}
      </div>
      {pairs.length > 0 && (
        <div className="row between" style={{ marginTop: 26 }}>
          <span className="muted small">Submitting saves every change first, then freezes each output’s template version, inputs and settings. Later template edits never change queued or finished outputs.
            {imageryOnly > 0 && <strong> {imageryOnly} creative output(s) are imagery only: their copy is not used.</strong>}</span>
          <button className="btn accent" onClick={submit} disabled={busy || !included.length || m.counts.blocked > 0}>{genLabel}</button>
        </div>
      )}
    </>
  );
}

function BatchList({ onOpen }: { onOpen: (id: string) => void }) {
  const [list, setList] = useState<any[] | null>(null);
  useEffect(() => { api.get<any[]>("/api/batches").then(setList).catch(() => setList([])); }, []);
  return (
    <>
      <div className="page-head"><div><span className="label">Generate</span><h1>Batch drafts</h1>
        <p className="lede">Select templates and products in the library, then continue to content review. Earlier drafts are kept here.</p></div>
        <Link className="btn" to="/templates">Open the library</Link></div>
      {list && list.length === 0 && <div className="empty"><h2>No batch yet</h2><p className="muted">Select templates and products in the library, then continue to content review.</p></div>}
      {list && list.length > 0 && (
        <table className="data"><thead><tr><th>Draft</th><th>Selection</th><th>Last change</th><th /></tr></thead>
          <tbody>{list.map((b) => <tr key={b.id}><td><strong>{b.name}</strong></td><td className="small">{b.template_versions.length} template(s) × {b.product_ids.length} product(s)</td>
            <td className="small">{new Date(b.updated_at).toLocaleString()}</td><td><button className="btn secondary small" onClick={() => onOpen(b.id)}>Open</button></td></tr>)}</tbody></table>
      )}
    </>
  );
}

function DefaultCopy({ role, value, onSave }: { role: string; value?: string; onSave: (v: string | null) => void }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => setV(value ?? ""), [value]);
  return (
    <div className="field">
      <span className="label">{role} for all outputs {value !== undefined && <button className="btn ghost small" onClick={() => onSave(null)}>clear</button>}</span>
      <input type="text" aria-label={`${role} for all outputs`} value={v} placeholder="not set" onChange={(e) => setV(e.target.value)} onBlur={() => v !== (value ?? "") && onSave(v)} dir="auto" />
    </div>
  );
}

function BulkApply({ m, roles, products, templates, selected, q, onDone }: { m: Matrix; roles: string[]; products: Record<string, Product>; templates: Record<string, Template>; selected: string[]; q: WriteQueue; onDone: (m: Matrix) => void }) {
  const [scope, setScope] = useState("all");
  const [role, setRole] = useState(roles[0] || "headline");
  const [val, setVal] = useState("");
  const toast = useToast();
  const go = () => {
    const [kind, ident] = scope.split(":");
    const sc = kind === "all" ? { kind } : kind === "product" ? { kind, product_id: ident } : kind === "template" ? { kind, template_id: ident } : { kind: "pairs", pair_ids: selected };
    // the key names the field written (all outputs = the batch default the field above edits too), so the newest wins
    const key = kind === "all" ? `batch:defaults.copy.${role}` : kind === "pairs" ? `bulk:pairs:${[...selected].sort().join(",")}:${role}` : `bulk:${scope}:${role}`;
    void q.run(key, async () => { onDone(await api.post<Matrix>(`/api/batches/${m.batch.id}/apply`, { scope: sc, copy: { [role]: val } })); },
      (ok) => { if (ok) toast("Applied — outputs you edited by hand keep their text"); }, { once: true });
  };
  return (
    <div className="stack">
      <div className="grid2">
        <label className="field"><span className="label">To</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="all">All outputs (batch default)</option>
            {m.batch.product_ids.map((id) => <option key={id} value={`product:${id}`}>Product: {products[id]?.name || id}</option>)}
            {m.batch.template_versions.map((x) => <option key={x.template_id} value={`template:${x.template_id}`}>Template: {templates[x.template_id]?.name || x.template_id}</option>)}
            <option value="pairs" disabled={!selected.length}>Selected rows ({selected.length})</option>
          </select></label>
        <label className="field"><span className="label">Slot</span><select value={role} onChange={(e) => setRole(e.target.value)}>{roles.map((r) => <option key={r}>{r}</option>)}</select></label>
      </div>
      <label className="field"><span className="label">Text <span className="muted">empty = deliberately empty</span></span><textarea rows={2} value={val} onChange={(e) => setVal(e.target.value)} dir="auto" /></label>
      <div><button className="btn secondary small" onClick={go} disabled={!roles.length}>Apply</button></div>
    </div>
  );
}

type Draft = { v: string | null } | null;
const asDraft = (x: unknown): Draft => (typeof x === "string" ? { v: x } : (x as Draft)); // earlier versions stored a bare string

function SlotEditor({ s, q, wkey, save, onUseDraft, onApprove, unsentKey }: {
  s: ResolvedSlot; q: WriteQueue; wkey: string; save: (v: string | null) => Promise<void>; onUseDraft: () => Promise<void>; onApprove: () => Promise<void>; unsentKey: string;
}) {
  // what this browser sent (or is about to send) and the server has not confirmed yet: kept until it is acknowledged
  const [stored, setUnsent] = useLocal<Draft>(unsentKey, null);
  const draft = asDraft(stored);
  const [v, setV] = useState(draft ? (draft.v ?? s.value ?? "") : (s.value ?? ""));
  // show the server's value whenever nothing of ours is pending (also after an explicit choice that did not change it)
  useEffect(() => { if (!draft) setV(s.value ?? ""); }, [s.value, !!draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const ackFor = (value: string | null) => (ok: boolean) => { if (ok) setUnsent((cur) => (asDraft(cur)?.v === value ? null : cur)); };
  const commit = (value: string | null, debounce: boolean) => {
    setUnsent({ v: value });
    if (debounce) q.schedule(wkey, () => save(value), 900, ackFor(value));
    else void q.run(wkey, () => save(value), ackFor(value));
  };
  useEffect(() => {
    if (draft) q.schedule(wkey, () => save(draft.v), 0, ackFor(draft.v)); // restored after a reload or a failed save: send it again
    return () => q.fire(wkey); // leaving: send a pending edit now instead of dropping it
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const change = (x: string) => { setV(x); commit(x, true); };
  const lim = s.limits || {};
  const isManual = s.source === "manual" || s.source === "AI draft";
  const srcId = useId();
  if (s.unused) {
    return (
      <div className="slot-field" style={{ opacity: 0.6 }}>
        <div className="row between"><span className="label">{s.role}</span><span className="slot-src">not used: imagery only</span></div>
        <p className="small muted" style={{ margin: 0 }}>This output generates imagery only, so its copy does not appear in the image. Choose live text or text drawn by the image model to use it.</p>
      </div>
    );
  }
  return (
    <div className={`slot-field ${s.problems.length ? "problem" : ""}`}>
      <div className="row between">
        <span className="label">{s.role}{s.required ? " · required" : ""}{lim.max_chars ? ` · ≤ ${lim.max_chars} chars` : ""}{lim.max_lines ? ` · ≤ ${lim.max_lines} line(s)` : ""}</span>
        <span className="slot-src" id={srcId}>{s.locked.length ? "locked by template" : s.hidden ? "hidden (no copy)" : s.source ? `from ${s.source}` : "not set"}{draft ? " · not saved yet" : ""}</span>
      </div>
      {s.locked.length ? <p className="small" style={{ whiteSpace: "pre-wrap" }}>{s.value}</p> : (
        <textarea aria-label={`${s.role} copy`} aria-describedby={srcId} rows={Math.max(1, Math.min(4, (v.match(/\n/g) || []).length + 1))} value={v} onChange={(e) => change(e.target.value)} dir="auto"
                  placeholder={s.template_text ? `reference text (not used unless you choose it): “${s.template_text.replace(/\n/g, " / ")}”` : "type copy for this output"} />
      )}
      {!s.locked.length && (
        <div className="row small" style={{ gap: 6, marginTop: 4 }}>
          {isManual && <button className="btn ghost small" onClick={() => commit(null, false)}>Use inherited value</button>}
          {!s.required && <button className="btn ghost small" onClick={() => { setV(""); commit("", false); }}>Leave empty</button>}
          {s.template_text && v !== s.template_text && <button className="btn ghost small" onClick={() => { setV(s.template_text || ""); commit(s.template_text || "", false); }}>Use reference text</button>}
          {s.source === "AI draft" && !s.approved && <button className="btn small" onClick={() => void q.run(`${wkey}:approve`, onApprove, undefined, { once: true })}>Approve AI draft</button>}
          <span className="muted">{(v || "").replace(/\n/g, "").length} chars</span>
        </div>
      )}
      {s.ai_draft && s.ai_draft.value !== s.value && (
        <div className="draft-box"><span className="label">AI draft{s.ai_draft.mock ? " (mock)" : ""}</span><div style={{ whiteSpace: "pre-wrap" }}>{s.ai_draft.value || <em>empty — {s.ai_draft.note}</em>}</div>
          <button className="btn secondary small" style={{ marginTop: 6 }}
                  onClick={() => { setUnsent(null); q.forget(wkey); void q.run(wkey, onUseDraft, undefined, { once: true }); }}>Use this draft (replaces this output’s text)</button></div>
      )}
      {s.problems.map((x) => <div key={x} className="small" style={{ color: "var(--crimson-ink)" }}>{x}</div>)}
    </div>
  );
}

function OutputEditor({ p, batchId, product, template, selected, onSelect, setPair, q, reload, onMatrix, flushOrSay }: {
  p: Pair; batchId: string; product?: Product; template?: Template; selected: boolean; onSelect: (on: boolean) => void;
  setPair: (pid: string, key: string, body: any, opts?: WriteOpts) => Promise<void | undefined>; q: WriteQueue; reload: () => void; onMatrix: (m: Matrix) => void;
  flushOrSay: (what: string) => Promise<boolean>;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const toast = useToast();
  const job = useJob(jobId, () => reload());
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const prev = p.preview && !p.preview.stale ? p.preview : null;
  const call = (path: string) => async () => { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/pairs/${p.pair_id}/${path}`)); };
  const canPreview = p.mode !== "creative" || p.creative_text === "overlay";
  return (
    <article className={`out-card ${p.included ? "" : "excluded"}`} aria-label={`${p.product?.name} on ${p.template?.name}`}>
      <div className="out-thumbs">
        {product?.primary_asset && <img src={product.primary_asset.thumb_url} alt={product.name} />}
        <img src={prev ? `/api/batches/${batchId}/pairs/${p.pair_id}/preview.png?h=${p.inputs_hash}` : template?.current_version?.thumb_url || template?.thumb_url}
             alt={prev ? "Preview of this output" : "Template"} />
        {canPreview && <button className="btn secondary small" onClick={async () => {
          if (!(await flushOrSay("Preview"))) return;
          try { const j = await api.post<any>(`/api/batches/${batchId}/pairs/${p.pair_id}/preview`); setJobId(j.id); } catch (e) { toast(errText(e), true); } }}>
          {prev ? "Re-check fit" : "Check fit & preview"}</button>}
        {job && job.status !== "completed" && <JobLine job={job} label="Preview" />}
        {prev && <span className={`tag ${prev.status === "overflow" ? "bad" : "ok"}`}>{prev.status === "overflow" ? "does not fit" : prev.status === "fitted" ? "fits (size reduced within rules)" : "fits"}</span>}
        {p.preview?.stale && <span className="tag">preview out of date</span>}
      </div>
      <div className="stack" style={{ gap: 10 }}>
        <div className="row between">
          <div className="row">
            <label className="check"><input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label="Select row" /></label>
            <StatusDot status={p.included ? p.status : ""} />
            <strong>{p.product?.name}</strong><span className="muted">×</span><strong>{p.template?.name}</strong>
            <span className="tag">v{p.template?.number}</span>{p.variant_index > 0 && <span className="tag">variant {p.variant_index + 1}</span>}
          </div>
          <div className="row">
            <label className="check small"><input type="checkbox" checked={p.included} onChange={(e) => setPair(p.pair_id, "included", { included: e.target.checked }, { once: true })} /> Include</label>
            <button className="btn ghost small" onClick={() => void q.run(`variant:${p.pair_id}`, async () => { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/variants`, { product_id: p.product_id, template_id: p.template_id })); }, undefined, { once: true })}>+ Variant</button>
          </div>
        </div>
        <div className="row small">
          <select aria-label="Mode" value={p.pair_mode || ""} onChange={(e) => setPair(p.pair_id, "mode", { mode: e.target.value || null }, { once: true })}>
            <option value="">Mode: batch default ({MODES[p.mode] ? p.mode : "adapt"})</option>
            {Object.entries(MODES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {p.mode === "creative" && (
            <select aria-label="Text in this artwork" value={p.pair_creative_text || ""} onChange={(e) => setPair(p.pair_id, "creative_text", { creative_text: e.target.value || null }, { once: true })}>
              <option value="">Text: batch default ({CREATIVE_TEXT[p.creative_text || "overlay"]})</option>
              {Object.entries(CREATIVE_TEXT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          )}
          <select aria-label="Language" value={p.pair_language || ""} onChange={(e) => setPair(p.pair_id, "language", { language: e.target.value || null }, { once: true })}>
            <option value="">Language: batch default ({p.language})</option><option value="en">English</option><option value="ar">Arabic</option></select>
          <span className="muted">{p.template?.canvas?.width} × {p.template?.canvas?.height} px</span>
        </div>
        {p.version_check?.needs_confirmation && (
          <div className="notice warn small">
            <strong>Template version changed (v{p.version_check.from_number} → v{p.version_check.to_number}).</strong> Some slots this output had text for differ. Choose where each one goes:
            {[...p.version_check.missing_slots, ...p.version_check.changed_slots].map((s: string) => (
              <div key={s} className="row" style={{ marginTop: 4 }}><code>{s}</code> →
                <input type="text" placeholder="new slot id, or leave empty to drop" value={mapping[s] ?? ""} onChange={(e) => setMapping({ ...mapping, [s]: e.target.value || null })} style={{ maxWidth: 260 }} /></div>))}
            <button className="btn small" style={{ marginTop: 6 }} onClick={() => { q.fireAll(); void q.run(`confirm-version:${p.pair_id}`, async () => { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/pairs/${p.pair_id}/confirm-version`, { mapping })); }, undefined, { once: true }); }}>Confirm mapping</button>
          </div>
        )}
        {(p.slots || []).map((s) => (
          <SlotEditor key={s.slot_id} s={s} q={q} wkey={`slot:${p.pair_id}:${s.slot_id}`} unsentKey={`dna.unsent.${p.pair_id}.${s.slot_id}`}
                      save={async (v) => { onMatrix(await api.patch<Matrix>(`/api/batches/${batchId}/pairs/${p.pair_id}`, { manual: { [s.slot_id]: v === null ? null : { value: v } } })); }}
                      onUseDraft={call(`use-draft/${s.slot_id}`)} onApprove={call(`approve/${s.slot_id}`)} />
        ))}
        {(p.slots || []).length === 0 && <p className="small muted">This template has no text slots.</p>}
        {p.image && <p className="small">Image slot <strong>{p.image.role}</strong> ← {p.mode === "creative_slot" ? "a generated scene of the product (provenance recorded)" : p.mode === "creative" ? "replaced by the generated artwork; the product photo is a reference for the provider" : "the product's primary photo (same frame, crop intent, mask and treatment)"}</p>}
        <label className="field" style={{ marginBottom: 0 }}><span className="label">Extra instructions for this output</span>
          <textarea rows={1} defaultValue={p.pair_instructions || ""} onBlur={(e) => e.target.value !== (p.pair_instructions || "") && setPair(p.pair_id, "instructions", { instructions: e.target.value || null })} /></label>
        {p.included && (p.problems.length > 0 || p.warnings.length > 0) && (
          <div className={`notice ${p.problems.length ? "bad" : "warn"} small`}>
            {p.problems.length > 0 && <><strong>Before generating:</strong><ul className="tight">{p.problems.map((x) => <li key={x}>{x}</li>)}</ul></>}
            {p.warnings.length > 0 && <><strong>Limitations:</strong><ul className="tight">{p.warnings.map((x) => <li key={x}>{x}</li>)}</ul></>}
          </div>
        )}
        {prev?.status === "overflow" && <div className="notice bad small"><strong>The copy does not fit:</strong><ul className="tight">{Object.entries(prev.fit?.overflow || {}).map(([k, x]: any) => <li key={k}>{k}: {x}</li>)}</ul>
          Options: shorten the copy, add an approved line break, allow a permitted smaller size in a template copy, or edit a template copy.</div>}
        <Dev data={{ pair_id: p.pair_id, inputs_hash: p.inputs_hash, instructions: p.instructions, fit: p.fit, creative_text: p.creative_text }} />
      </div>
    </article>
  );
}
