// Batch composer: products x template versions -> independently editable outputs, reviewed before anything is generated.
// Copy precedence: template defaults -> batch defaults -> product overrides -> pair overrides -> what you type per output.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, MODES, type Matrix, type Pair, type Product, type ResolvedSlot, type Template } from "../api";
import { useComposer } from "../components/Composer";
import { Dev, errText, JobLine, newKey, StatusDot, useJob, useLocal, useToast } from "../lib";
import { Icon } from "../components/ui";

export default function Generate() {
  const [params, setParams] = useSearchParams();
  const c = useComposer();
  const bid = params.get("batch") || c.batchId;
  const [m, setM] = useState<Matrix | null>(null);
  const [err, setErr] = useState("");
  const [products, setProducts] = useState<Record<string, Product>>({});
  const [templates, setTemplates] = useState<Record<string, Template>>({});
  const [fonts, setFonts] = useState<any[]>([]);
  const [selRows, setSelRows] = useState<string[]>([]);
  const [draftJob, setDraftJob] = useState<string | null>(null);
  const [submitKey, setSubmitKey] = useLocal<string | null>(`dna.submit.${bid}`, null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const toast = useToast();
  const load = () => bid ? api.get<Matrix>(`/api/batches/${bid}`).then((x) => { setM(x); setErr(""); }).catch((e) => setErr(errText(e))) : Promise.resolve();
  useEffect(() => { if (bid && !params.get("batch")) setParams({ batch: bid }, { replace: true }); load(); }, [bid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.get<Product[]>("/api/products").then((ps) => setProducts(Object.fromEntries(ps.map((p) => [p.id, p])))).catch(() => {});
    api.get<{ templates: Template[] }>("/api/templates").then((r) => setTemplates(Object.fromEntries(r.templates.map((t) => [t.id, t])))).catch(() => {});
    api.get<any[]>("/api/fonts").then(setFonts).catch(() => {});
  }, []);
  const dj = useJob(draftJob, (j) => { load(); toast(j.status === "completed" ? `${j.result?.drafts ?? 0} AI draft(s) ready to review` : "AI drafting did not complete", j.status !== "completed"); });
  const pairs = m?.pairs || [];
  const roles = useMemo(() => Array.from(new Set(pairs.flatMap((p) => (p.slots || []).map((s) => s.role)))), [pairs]);

  if (!bid) return <BatchList onOpen={(id) => { c.setBatchId(id); setParams({ batch: id }); }} />;
  if (err) return <div className="notice bad" role="alert">{err} <Link to="/templates">Back to the library</Link></div>;
  if (!m) return <p className="muted">Loading the batch…</p>;
  const b = m.batch;
  const patchBatch = async (changes: any) => { try { const x = await api.patch<Matrix>(`/api/batches/${b.id}`, { base_revision: b.revision, changes }); setM(x); } catch (e) { toast(errText(e), true); load(); } };
  const setPair = async (pid: string, body: any) => { try { setM(await api.patch<Matrix>(`/api/batches/${b.id}/pairs/${pid}`, body)); } catch (e) { toast(errText(e), true); } };
  const submit = async () => {
    setBusy(true);
    const key = submitKey || newKey();
    setSubmitKey(key);
    try {
      const r = await api.post<any>(`/api/batches/${b.id}/submit`, { idempotency_key: key, name: b.name });
      setSubmitKey(null);
      toast(r.duplicate ? "Already submitted — opening the run" : `Submitted ${r.outputs} output(s)`);
      nav(`/runs/${r.run_id}`);
    } catch (e) { toast(errText(e), true); setSubmitKey(null); load(); } finally { setBusy(false); }
  };
  const included = pairs.filter((p) => p.included);
  return (
    <>
      <div className="page-head">
        <div>
          <span className="label">Generate · content review</span>
          <h1 style={{ margin: 0 }}>
            <input aria-label="Batch name" className="h1-input" defaultValue={b.name} onBlur={(e) => e.target.value !== b.name && patchBatch({ name: e.target.value })}
                   style={{ font: "600 30px var(--serif)", border: 0, background: "transparent", padding: 0, width: "100%" }} />
          </h1>
          <p className="lede">{m.counts.proposed} proposed · <strong>{m.counts.included} included</strong> · {m.counts.excluded} excluded{m.counts.blocked ? <> · <span style={{ color: "var(--crimson)" }}>{m.counts.blocked} need attention</span></> : null}</p>
        </div>
        <div className="row">
          <Link className="btn secondary" to="/templates">Change selection</Link>
          <button className="btn accent" onClick={submit} disabled={busy || !included.length || m.counts.blocked > 0}>Generate {included.length} output{included.length === 1 ? "" : "s"}</button>
        </div>
      </div>

      <div className="summary-cards" aria-label="Batch summary">
        <div className="summary-card"><Icon name="layers" size={22} /><div><strong>{m.counts.proposed}</strong><small>Proposed outputs</small></div></div>
        <div className="summary-card"><Icon name="check" size={22} /><div><strong>{m.counts.included}</strong><small>Included in this run</small></div></div>
        <div className="summary-card"><Icon name="filter" size={22} /><div><strong>{m.counts.blocked}</strong><small>Need attention</small></div></div>
      </div>
      {included.some(p => p.mode === "creative") && <div className="notice warn small" style={{ marginBottom: 22 }} role="note"><strong>Creative reference makes imagery without text.</strong> Text slots are not added to creative images in this version. Choose editable template adaptation or a generated photo in the template to use your reviewed headings and CTA.</div>}
      <div className="grid2" style={{ marginBottom: 22 }}>
        <section className="card">
          <h3>Batch defaults <span className="muted small">apply to every output unless a later layer sets a value</span></h3>
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="seg" role="group" aria-label="Default mode">{Object.entries(MODES).map(([k, l]) => (
              <button key={k} aria-pressed={(b.defaults.mode || "adapt") === k} onClick={() => patchBatch({ defaults: { mode: k } })}>{l}</button>))}</div>
          </div>
          {b.defaults.mode !== "adapt" && !m.providers.image_generation && <div className="notice warn small" style={{ marginBottom: 10 }}>No image provider is configured: creative modes are blocked. <Link to="/settings">Settings</Link></div>}
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="seg" role="group" aria-label="Default language">
              <button aria-pressed={(b.defaults.language || "en") === "en"} onClick={() => patchBatch({ defaults: { language: "en" } })}>English</button>
              <button aria-pressed={b.defaults.language === "ar"} onClick={() => patchBatch({ defaults: { language: "ar" } })}>العربية Arabic</button>
            </div>
            {(b.defaults.language === "ar" || pairs.some((p) => p.pair_language === "ar")) && (
              <select aria-label="Arabic font" value={b.defaults.arabic_font || ""} onChange={(e) => patchBatch({ defaults: { arabic_font: e.target.value || null } })}>
                <option value="">Choose an Arabic-capable font…</option>
                {fonts.map((f) => <option key={f.sha256} value={f.sha256}>{f.names.full}</option>)}
              </select>
            )}
          </div>
          {roles.map((r) => <DefaultCopy key={r} role={r} value={b.defaults.copy?.[r]} onSave={(v) => patchBatch({ defaults: { copy: { [r]: v } } })} />)}
          <label className="field"><span className="label">Instructions for every output</span>
            <textarea rows={2} defaultValue={b.defaults.instructions || ""} onBlur={(e) => e.target.value !== (b.defaults.instructions || "") && patchBatch({ defaults: { instructions: e.target.value } })} /></label>
        </section>
        <section className="card">
          <h3>Apply to a group</h3>
          <BulkApply m={m} roles={roles} products={products} templates={templates} selected={selRows} onDone={setM} />
          <hr className="rule" />
          <h4>Draft copy with AI</h4>
          <p className="small muted">Claude drafts copy for the selected outputs (or all included). Drafts appear beside each field; nothing you typed is replaced, and a draft is unapproved until you review it.</p>
          <button className="btn secondary small" disabled={!m.providers.copy}
                  onClick={async () => { try { const j = await api.post<any>(`/api/batches/${b.id}/draft-copy`, { pair_ids: selRows.length ? selRows : included.map((p) => p.pair_id) }); setDraftJob(j.id); } catch (e) { toast(errText(e), true); } }}>
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
                        onSelect={(on) => setSelRows((x) => on ? [...x, p.pair_id] : x.filter((y) => y !== p.pair_id))} setPair={setPair} reload={load} onMatrix={setM} />
        ))}
      </div>
      {pairs.length > 0 && (
        <div className="row between" style={{ marginTop: 26 }}>
          <span className="muted small">Submitting freezes each output’s template version, inputs and settings. Later template edits never change queued or finished outputs.</span>
          <button className="btn accent" onClick={submit} disabled={busy || !included.length || m.counts.blocked > 0}>Generate {included.length} output{included.length === 1 ? "" : "s"}</button>
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

function BulkApply({ m, roles, products, templates, selected, onDone }: { m: Matrix; roles: string[]; products: Record<string, Product>; templates: Record<string, Template>; selected: string[]; onDone: (m: Matrix) => void }) {
  const [scope, setScope] = useState("all");
  const [role, setRole] = useState(roles[0] || "headline");
  const [val, setVal] = useState("");
  const toast = useToast();
  const go = async () => {
    const [kind, ident] = scope.split(":");
    const sc = kind === "all" ? { kind } : kind === "product" ? { kind, product_id: ident } : kind === "template" ? { kind, template_id: ident } : { kind: "pairs", pair_ids: selected };
    try { onDone(await api.post<Matrix>(`/api/batches/${m.batch.id}/apply`, { scope: sc, copy: { [role]: val } })); toast("Applied — outputs you edited by hand keep their text"); }
    catch (e) { toast(errText(e), true); }
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

function SlotEditor({ s, onSave, onUseDraft, onApprove, unsentKey }: { s: ResolvedSlot; onSave: (v: string | null) => void; onUseDraft: () => void; onApprove: () => void; unsentKey: string }) {
  const [unsent, setUnsent] = useLocal<string | null>(unsentKey, null);
  const [v, setV] = useState(unsent ?? s.value ?? "");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => { if (unsent === null) setV(s.value ?? ""); }, [s.value]); // eslint-disable-line react-hooks/exhaustive-deps
  const change = (x: string) => {
    setV(x); setUnsent(x);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { onSave(x); setUnsent(null); }, 900);
  };
  const lim = s.limits || {};
  const isManual = s.source === "manual" || s.source === "AI draft";
  const srcId = useId();
  return (
    <div className={`slot-field ${s.problems.length ? "problem" : ""}`}>
      <div className="row between">
        <span className="label">{s.role}{s.required ? " · required" : ""}{lim.max_chars ? ` · ≤ ${lim.max_chars} chars` : ""}{lim.max_lines ? ` · ≤ ${lim.max_lines} line(s)` : ""}</span>
        <span className="slot-src" id={srcId}>{s.locked.length ? "locked by template" : s.hidden ? "hidden (no copy)" : s.source ? `from ${s.source}` : "not set"}{unsent !== null ? " · saving…" : ""}</span>
      </div>
      {s.locked.length ? <p className="small" style={{ whiteSpace: "pre-wrap" }}>{s.value}</p> : (
        <textarea aria-label={`${s.role} copy`} aria-describedby={srcId} rows={Math.max(1, Math.min(4, (v.match(/\n/g) || []).length + 1))} value={v} onChange={(e) => change(e.target.value)} dir="auto"
                  placeholder={s.template_text ? `reference text (not used unless you choose it): “${s.template_text.replace(/\n/g, " / ")}”` : "type copy for this output"} />
      )}
      {!s.locked.length && (
        <div className="row small" style={{ gap: 6, marginTop: 4 }}>
          {isManual && <button className="btn ghost small" onClick={() => { setUnsent(null); onSave(null); }}>Use inherited value</button>}
          {!s.required && <button className="btn ghost small" onClick={() => { setV(""); setUnsent(null); onSave(""); }}>Leave empty</button>}
          {s.template_text && v !== s.template_text && <button className="btn ghost small" onClick={() => change(s.template_text || "")}>Use reference text</button>}
          {s.source === "AI draft" && !s.approved && <button className="btn small" onClick={onApprove}>Approve AI draft</button>}
          <span className="muted">{(v || "").replace(/\n/g, "").length} chars</span>
        </div>
      )}
      {s.ai_draft && s.ai_draft.value !== s.value && (
        <div className="draft-box"><span className="label">AI draft{s.ai_draft.mock ? " (mock)" : ""}</span><div style={{ whiteSpace: "pre-wrap" }}>{s.ai_draft.value || <em>empty — {s.ai_draft.note}</em>}</div>
          <button className="btn secondary small" style={{ marginTop: 6 }} onClick={onUseDraft}>Use this draft (replaces this output’s text)</button></div>
      )}
      {s.problems.map((x) => <div key={x} className="small" style={{ color: "var(--crimson-ink)" }}>{x}</div>)}
    </div>
  );
}

function OutputEditor({ p, batchId, product, template, selected, onSelect, setPair, reload, onMatrix }: {
  p: Pair; batchId: string; product?: Product; template?: Template; selected: boolean; onSelect: (on: boolean) => void;
  setPair: (pid: string, body: any) => Promise<void>; reload: () => void; onMatrix: (m: Matrix) => void;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const toast = useToast();
  const job = useJob(jobId, () => reload());
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const prev = p.preview && !p.preview.stale ? p.preview : null;
  const call = async (path: string) => { try { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/pairs/${p.pair_id}/${path}`)); } catch (e) { toast(errText(e), true); } };
  return (
    <article className={`out-card ${p.included ? "" : "excluded"}`} aria-label={`${p.product?.name} on ${p.template?.name}`}>
      <div className="out-thumbs">
        {product?.primary_asset && <img src={product.primary_asset.thumb_url} alt={product.name} />}
        <img src={prev ? `/api/batches/${batchId}/pairs/${p.pair_id}/preview.png?h=${p.inputs_hash}` : template?.current_version?.thumb_url || template?.thumb_url}
             alt={prev ? "Preview of this output" : "Template"} />
        {p.mode !== "creative" && <button className="btn secondary small" onClick={async () => { try { const j = await api.post<any>(`/api/batches/${batchId}/pairs/${p.pair_id}/preview`); setJobId(j.id); } catch (e) { toast(errText(e), true); } }}>
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
            <label className="check small"><input type="checkbox" checked={p.included} onChange={(e) => setPair(p.pair_id, { included: e.target.checked })} /> Include</label>
            <button className="btn ghost small" onClick={async () => { try { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/variants`, { product_id: p.product_id, template_id: p.template_id })); } catch (e) { toast(errText(e), true); } }}>+ Variant</button>
          </div>
        </div>
        <div className="row small">
          <select aria-label="Mode" value={p.pair_mode || ""} onChange={(e) => setPair(p.pair_id, { mode: e.target.value || null })}>
            <option value="">Mode: batch default ({MODES[p.mode] ? p.mode : "adapt"})</option>
            {Object.entries(MODES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <select aria-label="Language" value={p.pair_language || ""} onChange={(e) => setPair(p.pair_id, { language: e.target.value || null })}>
            <option value="">Language: batch default ({p.language})</option><option value="en">English</option><option value="ar">Arabic</option></select>
          <span className="muted">{p.template?.canvas?.width} × {p.template?.canvas?.height} px</span>
        </div>
        {p.version_check?.needs_confirmation && (
          <div className="notice warn small">
            <strong>Template version changed (v{p.version_check.from_number} → v{p.version_check.to_number}).</strong> Some slots this output had text for differ. Choose where each one goes:
            {[...p.version_check.missing_slots, ...p.version_check.changed_slots].map((s: string) => (
              <div key={s} className="row" style={{ marginTop: 4 }}><code>{s}</code> →
                <input type="text" placeholder="new slot id, or leave empty to drop" value={mapping[s] ?? ""} onChange={(e) => setMapping({ ...mapping, [s]: e.target.value || null })} style={{ maxWidth: 260 }} /></div>))}
            <button className="btn small" style={{ marginTop: 6 }} onClick={async () => { try { onMatrix(await api.post<Matrix>(`/api/batches/${batchId}/pairs/${p.pair_id}/confirm-version`, { mapping })); } catch (e) { toast(errText(e), true); } }}>Confirm mapping</button>
          </div>
        )}
        {(p.slots || []).map((s) => (
          <SlotEditor key={s.slot_id} s={s} unsentKey={`dna.unsent.${p.pair_id}.${s.slot_id}`}
                      onSave={(v) => setPair(p.pair_id, { manual: { [s.slot_id]: v === null ? null : { value: v } } })}
                      onUseDraft={() => call(`use-draft/${s.slot_id}`)} onApprove={() => call(`approve/${s.slot_id}`)} />
        ))}
        {(p.slots || []).length === 0 && <p className="small muted">This template has no text slots.</p>}
        {p.image && <p className="small">Image slot <strong>{p.image.role}</strong> ← {p.mode === "creative_slot" ? "a generated scene of the product (provenance recorded)" : p.mode === "creative" ? "used as a reference for the provider" : "the product's primary photo (same frame, crop intent, mask and treatment)"}</p>}
        <label className="field" style={{ marginBottom: 0 }}><span className="label">Extra instructions for this output</span>
          <textarea rows={1} defaultValue={p.pair_instructions || ""} onBlur={(e) => e.target.value !== (p.pair_instructions || "") && setPair(p.pair_id, { instructions: e.target.value || null })} /></label>
        {p.included && (p.problems.length > 0 || p.warnings.length > 0) && (
          <div className={`notice ${p.problems.length ? "bad" : "warn"} small`}>
            {p.problems.length > 0 && <><strong>Before generating:</strong><ul className="tight">{p.problems.map((x) => <li key={x}>{x}</li>)}</ul></>}
            {p.warnings.length > 0 && <><strong>Limitations:</strong><ul className="tight">{p.warnings.map((x) => <li key={x}>{x}</li>)}</ul></>}
          </div>
        )}
        {prev?.status === "overflow" && <div className="notice bad small"><strong>The copy does not fit:</strong><ul className="tight">{Object.entries(prev.fit?.overflow || {}).map(([k, x]: any) => <li key={k}>{k}: {x}</li>)}</ul>
          Options: shorten the copy, add an approved line break, allow a permitted smaller size in a template copy, or edit a template copy.</div>}
        <Dev data={{ pair_id: p.pair_id, inputs_hash: p.inputs_hash, instructions: p.instructions, fit: p.fit }} />
      </div>
    </article>
  );
}
