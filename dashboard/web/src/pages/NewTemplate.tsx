// New template: a real, resumable creation workflow. Every step saves to the server draft; ?id= resumes it.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, READINESS, type Asset, type Template } from "../api";
import AssetIntake from "../components/AssetIntake";
import CompareViewer from "../components/CompareViewer";
import ElementCanvas, { type El } from "../components/ElementCanvas";
import type { ModelView } from "../components/Inspector";
import { Dev, errText, Events, JobLine, useJob, useToast } from "../lib";
import { Icon, PageHeader } from "../components/ui";

const STEPS = [["purpose", "Name and purpose"], ["scan", "Scan"], ["rules", "Review rules"], ["rebuild", "Rebuild and compare"], ["save", "Save to library"]] as const;
type Step = (typeof STEPS)[number][0];
const ORDER: Record<string, number> = { purpose: 0, scan: 1, rules: 2, rebuild: 3, save: 4, saved: 5 };
const PURPOSE: [string, string, string][] = [
  ["character", "Character", "e.g. quiet, editorial, premium"], ["goal", "Goal", "What the design is for"], ["theme", "Theme", "Visual theme or mood"],
  ["audience_assumptions", "Audience / use", "Who it addresses (your words)"], ["channels", "Channel", "e.g. Instagram 4:5 feed, print A4"],
  ["literal_message", "Message", "What it says, literally"], ["usage", "When and where it is useful", "Launches, seasonal sales…"],
  ["unsuitable_for", "Not suitable for", "Optional"], ["preserve", "What should this template preserve?", "e.g. the serif headline, the red accent, the generous margins"],
];
const ROLES = ["headline", "subheadline", "body", "kicker", "label", "cta", "price", "caption", "legal", "product", "hero", "accent", "panel", "button", "logo", "decoration"];

export default function NewTemplate() {
  const [params, setParams] = useSearchParams();
  const id = params.get("id");
  const [t, setT] = useState<Template | null>(null);
  const [err, setErr] = useState("");
  const load = () => id && api.get<Template>(`/api/templates/${id}`).then((x) => { setT(x); setErr(""); }).catch((e) => setErr(errText(e)));
  useEffect(() => { setT(null); load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!id) return <Inspiration onCreated={(tid) => setParams({ id: tid })} via={params.get("via")} />;
  if (err) return <div className="notice bad">{err}</div>;
  if (!t) return <p className="muted">Loading draft…</p>;
  return <Wizard t={t} reload={load} setT={setT} />;
}

function Inspiration({ onCreated, via }: { onCreated: (id: string) => void; via: string | null }) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [support, setSupport] = useState<Asset[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const create = async () => {
    if (!asset) return;
    setBusy(true);
    try {
      const r = await api.post<Template>("/api/templates", { asset_id: asset.id, name: name.trim() || asset.original_name.replace(/\.[a-z0-9]+$/i, ""),
        supporting_asset_ids: support.map((s) => s.id) });
      toast("Draft created and saved"); onCreated(r.id);
    } catch (e) { toast(errText(e), true); } finally { setBusy(false); }
  };
  const m = asset?.metadata || {};
  return (
    <>
      <PageHeader eyebrow="Build your library · start with a reference" title={<>Add inspiration<span className="title-dot">.</span></>} description="Upload a finished design, paste an image or add a link. We’ll help you turn its parts into a reusable template." actions={<Link className="btn secondary" to="/templates"><Icon name="layers" size={16} />Back to library</Link>} />
      <div className="split">
        <div className="stack">
          {!asset ? (
            <>
              {via === "paste" && <div className="notice">Press ⌘/Ctrl+V to paste an image from your clipboard.</div>}
              {via === "link" && <div className="notice">Paste a direct image link, or a public page link to choose one of the images it declares.</div>}
              <AssetIntake role="inspiration" onAdded={(a) => { setAsset(a[0]); setName(a[0].original_name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ")); }} />
            </>
          ) : (
            <div className="viewer"><img className="checker" src={asset.preview_url} alt="Inspiration preview (oriented sRGB copy)" /></div>
          )}
        </div>
        <div className="stack">
          {asset ? (
            <div className="card">
              <span className="label">Intake</span>
              <dl className="kv small">
                <dt>File</dt><dd>{asset.original_name} · {m.format} · {(asset.bytes / 1e6).toFixed(2)} MB</dd>
                <dt>Canvas</dt><dd>{asset.width} × {asset.height} px</dd>
                <dt>Orientation</dt><dd>{m.exif_orientation && m.exif_orientation !== 1 ? `EXIF ${m.exif_orientation} applied` : "as stored"}</dd>
                <dt>Colour</dt><dd>{m.icc_profile ? `embedded “${m.icc_profile}”, converted to sRGB for comparison` : "untagged: assumed sRGB"}</dd>
                {m.first_frame_only && <><dt>Animation</dt><dd><span className="tag warn">first frame only</span> of {m.frames}</dd></>}
                <dt>Source</dt><dd>{asset.source_kind === "page_image" ? <>image from <a href={asset.page_url} target="_blank" rel="noreferrer">{asset.provenance?.page_title || asset.page_url}</a></> : asset.source_kind}</dd>
              </dl>
              <label className="field" style={{ marginTop: 12 }}><span className="label">Template name</span>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Botanical editorial" /></label>
              <details><summary className="small">Supporting images (optional)</summary>
                <p className="small muted">Other states or crops of the same design. They are kept with the draft as context; the primary image is what gets scanned.</p>
                <div className="thumbs">{support.map((s) => <div className="thumb" key={s.id}><img src={s.thumb_url} alt={s.original_name} /></div>)}</div>
                <AssetIntake role="inspiration" multiple compact listenPaste={false} onAdded={(a) => setSupport((x) => [...x, ...a])} label="Add supporting images" />
              </details>
              <div className="row" style={{ marginTop: 14 }}>
                <button className="btn" onClick={create} disabled={busy}>{busy ? "Creating…" : "Create draft template"}</button>
                <button className="btn ghost" onClick={() => setAsset(null)}>Choose another</button>
              </div>
            </div>
          ) : (
            <div className="card flat scan-intro">
              <span className="label">What happens next</span>
              <ol>
                <li>Name it and describe what it is for (your words are labelled as yours).</li>
                <li>Scan: Claude proposes elements, or you draw them; the engine measures each one.</li>
                <li>Review what was measured, what was inferred and what stays unknown.</li>
                <li>Rebuild the design and compare it with the original, pixel by pixel.</li>
                <li>Save it to the library at the level it actually reached.</li>
              </ol>
              <img className="help-art" src="/api/help/case-inspiration-to-template.png" alt="Illustration: an inspiration image becoming a template" />
              <p className="illustration-note">Illustration of the concept — not a measured template.</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Wizard({ t, reload, setT }: { t: Template; reload: () => void; setT: (t: Template) => void }) {
  const draft = t.draft || {};
  const savedStep = (draft.step as string) || "purpose";
  const [step, setStep] = useState<Step>((["purpose", "scan", "rules", "rebuild", "save"].includes(savedStep) ? savedStep : savedStep === "saved" ? "save" : "purpose") as Step);
  const reached = Math.max(ORDER[savedStep] ?? 0, ORDER[step]);
  const toast = useToast();
  const save = async (changes: Record<string, any>, quiet = false) => {
    try { const x = await api.patch<Template>(`/api/templates/${t.id}/draft`, { base_revision: t.draft_revision, changes }); setT(x); if (!quiet) toast("Draft saved"); return x; }
    catch (e) { toast(errText(e), true); if ((e as any).code === "stale_draft") reload(); return null; }
  };
  const go = (s: Step) => { setStep(s); save({ draft: { step: s } }, true); window.scrollTo({ top: 0 }); };
  return (
    <>
      <div className="page-head">
        <div><span className="label">New template · draft</span><h1>{t.name}</h1>
          <p className="lede">Saved automatically as you go. You can leave and return to this draft from the library.</p></div>
        <div className="row"><span className="tag">{READINESS[t.readiness] || t.readiness}</span><Link className="btn secondary" to={`/templates/${t.id}`}>Open template page</Link></div>
      </div>
      <ol className="steps" aria-label="Steps">
        <li className="done">Add inspiration</li>
        {STEPS.map(([k, label], i) => (
          <li key={k} className={step === k ? "current" : i + 1 <= reached ? "done" : ""}>
            <button onClick={() => go(k)} aria-current={step === k ? "step" : undefined}>{label}</button>
          </li>
        ))}
      </ol>
      {draft.last_job_problem && (
        <div className="notice warn" style={{ marginBottom: 16 }}>Last step ({draft.last_job_problem.kind}) ended as <strong>{draft.last_job_problem.status.replace("_", " ")}</strong>:{" "}
          {draft.last_job_problem.error?.message || "see the details below"}</div>
      )}
      {step === "purpose" && <Purpose t={t} save={save} next={() => go("scan")} />}
      {step === "scan" && <Scan t={t} save={save} reload={reload} next={() => go("rules")} />}
      {step === "rules" && <Rules t={t} reload={reload} next={() => go("rebuild")} />}
      {step === "rebuild" && <Rebuild t={t} reload={reload} next={() => go("save")} />}
      {step === "save" && <Save t={t} reload={reload} />}
    </>
  );
}

function Purpose({ t, save, next }: { t: Template; save: (c: any, q?: boolean) => Promise<Template | null>; next: () => void }) {
  const [vals, setVals] = useState<Record<string, { value: string; status: string }>>(() => Object.fromEntries(PURPOSE.map(([k]) => {
    const p: any = t.passport?.[k];
    return [k, { value: p?.value ? String(p.value) : "", status: p?.status || "user_supplied" }];
  })));
  const [name, setName] = useState(t.name);
  const commit = (quiet = true) => save({ name, passport: Object.fromEntries(Object.entries(vals).filter(([, v]) => v.value.trim() || true)
    .map(([k, v]) => [k, v.value.trim() ? { value: v.value.trim(), status: v.status } : { value: null, status: "unknown" }])) }, quiet);
  return (
    <div className="split">
      <div className="card">
        <label className="field"><span className="label">Name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => commit()} /></label>
        {PURPOSE.map(([k, label, ph]) => {
          const v = vals[k];
          const suggested = v.status === "suggested";
          return (
            <label key={k} className="field">
              <span className="label">{label}{v.value && <span className={`tag ${suggested ? "warn" : ""}`}>{suggested ? "suggested by Claude" : v.status.replace("_", " ")}</span>}</span>
              <textarea rows={k === "preserve" ? 3 : 2} value={v.value} placeholder={ph}
                        onChange={(e) => setVals({ ...vals, [k]: { value: e.target.value, status: "user_supplied" } })} onBlur={() => commit()} />
              {suggested && <span className="row"><button type="button" className="btn ghost small" onClick={() => { setVals({ ...vals, [k]: { ...v, status: "user_confirmed" } }); setTimeout(() => commit(), 0); }}>Accept suggestion</button>
                <span className="hint">A suggestion stays labelled as one until you accept or edit it.</span></span>}
            </label>
          );
        })}
        <div className="row"><button className="btn secondary" onClick={() => commit(false)}>Save draft</button><button className="btn" onClick={async () => { await commit(); next(); }}>Continue to scan →</button></div>
      </div>
      <div className="stack sticky">
        <div className="viewer"><img className="checker" src={`/api/templates/${t.id}/files/work/source/canonical.png`} alt="Inspiration" /></div>
        <p className="small muted">Your words are recorded as <em>user supplied</em>; anything Claude proposes is labelled <em>suggested</em> until you accept it. Message and intended response are interpretations, never measured facts.</p>
      </div>
    </div>
  );
}

function useDebounced(fn: () => void, deps: unknown[], ms = 700) {
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } const id = setTimeout(fn, ms); return () => clearTimeout(id); }, deps); // eslint-disable-line react-hooks/exhaustive-deps
}

function Scan({ t, save, reload, next }: { t: Template; save: (c: any, q?: boolean) => Promise<Template | null>; reload: () => void; next: () => void }) {
  const d = t.draft || {};
  const [els, setEls] = useState<El[]>(d.elements || []);
  const [sel, setSel] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [analysisOk, setAnalysisOk] = useState<boolean | null>(null);
  const [dirty, setDirty] = useState(false);
  const toast = useToast();
  const job = useJob(jobId, () => { reload(); });
  useEffect(() => { setEls(t.draft?.elements || []); }, [t.draft?.elements]); // server is the source of truth after jobs
  useEffect(() => { api.get<any[]>("/api/providers").then((ps) => setAnalysisOk(ps.some((p) => p.capabilities.includes("analysis") && p.configured))).catch(() => setAnalysisOk(false)); }, []);
  useDebounced(() => { if (dirty) { save({ draft: { elements: els } }, true); setDirty(false); } }, [els, dirty]);
  const W = t.width || 1, H = t.height || 1;
  const upd = (k: string, patch: Partial<El>) => { setEls((xs) => xs.map((x) => (x.key === k ? { ...x, ...patch, edited: true } : x))); setDirty(true); };
  const cur = els.find((x) => x.key === sel);
  const run = async (path: string) => {
    try { if (dirty) { await save({ draft: { elements: els } }, true); setDirty(false); } const j = await api.post<any>(path, {}); setJobId(j.id); }
    catch (e) { toast(errText(e), true); }
  };
  const meas = d.measure, val = d.validation;
  const accepted = els.filter((x) => x.status !== "rejected");
  return (
    <div className="split">
      <div className="stack">
        <div className="row between">
          <div className="row">
            <button className="btn" onClick={() => run(`/api/templates/${t.id}/analyze`)} disabled={!analysisOk || !!t.busy}
                    title={analysisOk ? "" : "Add an Anthropic API key in Settings to enable assisted scanning"}>Analyze with Claude</button>
            <button className={`btn ${drawing ? "accent" : "secondary"}`} aria-pressed={drawing} onClick={() => setDrawing(!drawing)}>{drawing ? "Drawing: drag a box" : "Draw element"}</button>
          </div>
          {analysisOk === false && <Link className="small" to="/settings">Assisted scan needs a Claude key →</Link>}
        </div>
        <ElementCanvas src={`/api/templates/${t.id}/files/work/source/canonical.png`} width={W} height={H} elements={els} selected={sel} onSelect={setSel}
                       onChange={(k, b) => upd(k, { bbox: b })} drawing={drawing}
                       onDrawn={(b) => { const key = `e${Date.now().toString(36).slice(-5)}`; setEls((xs) => [...xs, { key, type: "text", role: "headline", bbox: b, text: "", align: "left", slot: true, status: "accepted", source: "user" }]); setSel(key); setDrawing(false); setDirty(true); }} />
        <p className="small muted">Boxes say where to measure. Positions, colours, fonts and sizes come from the engine’s tools; proposals are never stored as measurements.
          {d.analysis_meta?.mock && <strong> These proposals come from the mock provider (test only).</strong>}</p>
        {job && <div className="card flat"><JobLine job={job} label={job.kind === "template.analyze" ? "Analysis" : "Measurement"} /><Events job={job} /></div>}
      </div>
      <div className="stack sticky">
        <div className="card">
          <div className="row between"><span className="label">{accepted.length} element(s) to measure · {els.filter((x) => x.status === "proposed").length} unreviewed</span>
            {els.some((x) => x.status === "proposed") && <button className="btn ghost small" onClick={() => { setEls((xs) => xs.map((x) => x.status === "proposed" ? { ...x, status: "accepted" } : x)); setDirty(true); }}>Accept all proposals</button>}</div>
          {!els.length && <p className="small muted">No elements yet. Analyze with Claude, or draw boxes around each text block, photo, panel or logo.</p>}
          {cur ? (
            <div className="stack" style={{ marginTop: 10 }}>
              <div className="row between"><strong>{cur.role || cur.type}</strong>{cur.source && <span className="tag">{cur.source === "user" ? "drawn by you" : cur.source === "mock" ? "mock proposal" : `proposed${cur.confidence ? ` · ${cur.confidence}` : ""}`}</span>}</div>
              <div className="grid2">
                <label className="field"><span className="label">Type</span>
                  <select value={cur.type} onChange={(e) => upd(cur.key, { type: e.target.value as El["type"] })}>
                    {["text", "image", "shape", "logo", "background"].map((x) => <option key={x}>{x}</option>)}</select></label>
                <label className="field"><span className="label">Role</span>
                  <input type="text" list="roles" value={cur.role} onChange={(e) => upd(cur.key, { role: e.target.value })} /></label>
              </div>
              <datalist id="roles">{ROLES.map((r) => <option key={r} value={r} />)}</datalist>
              {cur.type === "text" && (
                <>
                  <label className="field"><span className="label">Exact text <span className="muted">line breaks matter</span></span>
                    <textarea rows={3} value={cur.text || ""} onChange={(e) => upd(cur.key, { text: e.target.value })} dir="auto" /></label>
                  <div className="seg" role="group" aria-label="Alignment">
                    {(["left", "center", "right"] as const).map((a) => <button key={a} aria-pressed={(cur.align || "left") === a} onClick={() => upd(cur.key, { align: a })}>{a}</button>)}</div>
                </>
              )}
              <div className="row small mono">
                {["x", "y", "w", "h"].map((k, i) => (
                  <label key={k} className="row" style={{ gap: 4 }}>{k}<input type="number" style={{ width: 76 }} value={Math.round(cur.bbox[i])}
                    onChange={(e) => { const b = [...cur.bbox]; b[i] = +e.target.value; upd(cur.key, { bbox: b }); }} /></label>))}
              </div>
              <label className="check"><input type="checkbox" checked={cur.slot !== false} onChange={(e) => upd(cur.key, { slot: e.target.checked })} /> Replaceable in new outputs (slot)</label>
              {cur.note && <p className="small muted">Note: {cur.note}</p>}
              <div className="row">
                {cur.status !== "accepted" && <button className="btn small" onClick={() => upd(cur.key, { status: "accepted" })}>Accept</button>}
                {cur.status !== "rejected" && <button className="btn secondary small" onClick={() => upd(cur.key, { status: "rejected" })}>Reject</button>}
                <button className="btn ghost small" onClick={() => { setEls((xs) => xs.filter((x) => x.key !== cur.key)); setSel(null); setDirty(true); }}>Delete</button>
              </div>
            </div>
          ) : els.length > 0 && <p className="small muted" style={{ marginTop: 8 }}>Select a box to review it.</p>}
          <hr className="rule" />
          <ul className="plain small" style={{ maxHeight: 220, overflow: "auto" }}>
            {els.map((x) => <li key={x.key}><button className="btn ghost small" onClick={() => setSel(x.key)} aria-pressed={sel === x.key}>
              <span className={`tag ${x.status === "rejected" ? "bad" : x.status === "proposed" ? "warn" : "ok"}`}>{x.status || "accepted"}</span> {x.type} · {x.role}{x.text ? ` “${x.text.slice(0, 24)}”` : ""}</button></li>)}
          </ul>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => run(`/api/templates/${t.id}/measure`)} disabled={!accepted.length || !!t.busy || els.some((x) => x.status === "proposed")}>Measure accepted elements</button>
            {els.some((x) => x.status === "proposed") && <span className="small muted">Review every proposal first.</span>}
          </div>
        </div>
        {meas && (
          <div className="card">
            <span className="label">Measurement results</span>
            <ul className="plain small">{Object.entries(meas.elements || {}).map(([k, r]: any) => <li key={k} className="row" style={{ gap: 6 }}>
              <span className={`tag ${r.status === "unknown" ? "bad" : r.status === "raster" ? "warn" : "ok"}`}>{r.status}</span> <strong>{k}</strong> {r.detail}</li>)}</ul>
            {meas.warnings?.length > 0 && <div className="notice warn small"><ul className="tight">{meas.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul></div>}
            {val && <p className="small">{val.valid ? "Model validates." : `Model has ${val.errors.length} validation error(s).`} Editability: <strong>{val.editability?.overall}</strong></p>}
            <div className="row"><button className="btn" onClick={next}>Review rules →</button></div>
            <Dev data={{ measure: meas, validation: val }} />
          </div>
        )}
      </div>
    </div>
  );
}

function Rules({ t, reload, next }: { t: Template; reload: () => void; next: () => void }) {
  const [m, setM] = useState<ModelView | null>(null);
  const [slots, setSlots] = useState<Record<string, any>>({});
  const [copy, setCopy] = useState<Record<string, string>>(t.draft?.default_copy || {});
  const [instr, setInstr] = useState<string>(t.draft?.default_instructions || "");
  const [locks, setLocks] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState<boolean>(!!t.draft?.review_confirmed);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    api.get<ModelView>(`/api/templates/${t.id}/model?source=work`).then((x) => {
      setM(x);
      const nodes = Object.fromEntries(x.scene.nodes.map((n: any) => [n.id, n]));
      setSlots(Object.fromEntries(x.scene.slots.map((s: any) => [s.id, { id: s.id, required: s.limits?.required ?? (s.type === "text" && ["headline", "title"].includes(s.role)),
        max_chars: s.limits?.max_chars || "", max_lines: s.limits?.max_lines || "", fit_policy: nodes[s.node]?.fit?.policy || "strict", min_size: nodes[s.node]?.fit?.min_size || "" }])));
      setLocks(x.scene.locks.filter((l: any) => l.kind === "property").map((l: any) => l.target));
    }).catch((e) => toast(errText(e), true));
  }, [t.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return <p className="muted">Loading the measured model…</p>;
  if (!m.scene.nodes.length) return <div className="notice warn">Nothing has been measured yet. Go back to Scan and measure the accepted elements.</div>;
  const nodes = Object.fromEntries(m.scene.nodes.map((n: any) => [n.id, n]));
  const submit = async () => {
    setBusy(true);
    try {
      const body = { base_revision: t.draft_revision, review_confirmed: confirmed, default_copy: copy, default_instructions: instr,
        slots: Object.values(slots).map((s: any) => ({ id: s.id, required: s.required, max_chars: s.max_chars || null, max_lines: s.max_lines || null,
          ...(nodes[m.scene.slots.find((x: any) => x.id === s.id).node]?.type === "text" ? { fit_policy: s.fit_policy, min_size: s.min_size || null } : {}) })),
        locks: locks.map((x) => ({ target: x, kind: "property", hard: true })) };
      await api.put(`/api/templates/${t.id}/rules`, body);
      toast("Rules saved and validated"); reload(); next();
    } catch (e) { toast(errText(e), true); reload(); } finally { setBusy(false); }
  };
  const val = t.draft?.validation;
  return (
    <div className="stack">
      <div className="card">
        <h3>What the scan found</h3>
        <p className="small muted">Every category has a result: measured by a tool, observed/confirmed, inferred (a hypothesis), unknown, or not applicable. Unknown is never treated as a pass.</p>
        <table className="data"><thead><tr><th>Category</th><th>Status</th><th>Finding</th></tr></thead><tbody>
          {m.constants.categories.map((c) => { const e = m.scene.scan.coverage[c]; return (
            <tr key={c}><td>{c.replace(/_/g, " ")}</td><td><span className={`tag ${!e ? "bad" : e.status === "unknown" ? "warn" : ""}`}>{e?.status || "missing"}</span></td>
              <td className="small">{e?.note}{e?.facets && <span className="muted"> · {Object.entries(e.facets).map(([k, f]: any) => `${k.replace(/_/g, " ")}: ${f.status}`).join(", ")}</span>}</td></tr>); })}
        </tbody></table>
      </div>
      <div className="card">
        <h3>Slots: what can change in new outputs</h3>
        <table className="data"><thead><tr><th>Slot</th><th>Required</th><th>Max chars</th><th>Max lines</th><th>Fit</th><th>Default copy</th></tr></thead><tbody>
          {m.scene.slots.map((s: any) => { const v = slots[s.id] || {}; const n = nodes[s.node]; const set = (p: any) => setSlots({ ...slots, [s.id]: { ...v, ...p } }); return (
            <tr key={s.id}>
              <td><strong>{s.role}</strong> <span className="muted small">{s.type}</span>{n?.content && <div className="small muted">reference text: “{n.content.slice(0, 40)}”</div>}</td>
              <td><input type="checkbox" aria-label={`${s.role} required`} checked={!!v.required} onChange={(e) => set({ required: e.target.checked })} /></td>
              <td>{s.type === "text" && <input type="number" aria-label={`${s.role} max characters`} style={{ width: 80 }} value={v.max_chars} onChange={(e) => set({ max_chars: e.target.value })} />}</td>
              <td>{s.type === "text" && <input type="number" aria-label={`${s.role} max lines`} style={{ width: 70 }} value={v.max_lines} onChange={(e) => set({ max_lines: e.target.value })} />}</td>
              <td>{s.type === "text" && <div className="stack" style={{ gap: 4 }}>
                <select aria-label={`${s.role} fit policy`} value={v.fit_policy} onChange={(e) => set({ fit_policy: e.target.value })}><option value="strict">strict</option><option value="fit">may shrink to…</option></select>
                {v.fit_policy === "fit" && <input type="number" aria-label="Minimum size px" placeholder={`min px (< ${n?.font?.size})`} value={v.min_size} onChange={(e) => set({ min_size: e.target.value })} />}</div>}</td>
              <td>{s.type === "text" && <input type="text" aria-label={`${s.role} default copy`} placeholder="none (must be supplied)" value={copy[s.id] || ""} onChange={(e) => setCopy({ ...copy, [s.id]: e.target.value })} />}</td>
            </tr>); })}
        </tbody></table>
        <p className="small muted">The reference’s own text is design evidence, not product copy: it is only used for a new output if you set it as a default here.</p>
        <label className="field"><span className="label">Default instructions for outputs</span><textarea rows={2} value={instr} onChange={(e) => setInstr(e.target.value)} placeholder="e.g. keep the copy short and calm; no exclamation marks" /></label>
        <div className="field"><span className="label">Locks (hard: changes are refused)</span>
          <div className="row">{["layout", "typography", "color", "background", "effects"].map((c) => (
            <label key={c} className="check"><input type="checkbox" checked={locks.includes(c)} onChange={(e) => setLocks(e.target.checked ? [...locks, c] : locks.filter((x) => x !== c))} /> {c}</label>))}</div></div>
        <label className="check"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> I reviewed these findings. Mark the scan complete (unknowns stay unknown).</label>
        {val && !val.valid && <div className="notice bad small" style={{ marginTop: 10 }}><strong>Validation</strong><ul className="tight">{val.errors.slice(0, 8).map((x: string) => <li key={x}>{x}</li>)}</ul></div>}
        {val?.passport && !val.passport.complete && <p className="small muted">Passport still missing: {val.passport.missing.join(", ")}.</p>}
        <div className="row" style={{ marginTop: 12 }}><button className="btn" onClick={submit} disabled={busy}>Save rules and continue →</button></div>
      </div>
    </div>
  );
}

function Rebuild({ t, reload, next }: { t: Template; reload: () => void; next: () => void }) {
  const [mode, setMode] = useState<"editable" | "exact">("editable");
  const [jobId, setJobId] = useState<string | null>(null);
  const toast = useToast();
  const job = useJob(jobId, () => reload());
  const st = t.draft?.staged;
  const start = async () => { try { const j = await api.post<any>(`/api/templates/${t.id}/rebuild`, { mode }); setJobId(j.id); } catch (e) { toast(errText(e), true); } };
  const v = st?.verdict;
  return (
    <div className="split">
      <div className="stack">
        {st ? <CompareViewer arts={{ reference: "source/canonical.png", baseline: st.baseline, side_by_side: st.artifacts?.side_by_side, overlay_50: st.artifacts?.overlay_50,
          diff_heatmap: st.artifacts?.diff_heatmap }} fileUrl={(rel) => `/api/templates/${t.id}/files/stage:${st.stage_id}/${rel}`} />
          : <div className="viewer"><img src={`/api/templates/${t.id}/files/work/source/canonical.png`} alt="Reference" /></div>}
      </div>
      <div className="stack sticky">
        <div className="card">
          <h3>Rebuild and compare</h3>
          <p className="small muted">The engine renders the measured model in its pinned browser and compares the result with the reference. This happens in a staging copy: no saved version changes until you accept it.</p>
          <div className="seg" role="group" aria-label="Profile">
            <button aria-pressed={mode === "editable"} onClick={() => setMode("editable")}>Editable match (declared tolerances)</button>
            <button aria-pressed={mode === "exact"} onClick={() => setMode("exact")}>Exact pixels</button>
          </div>
          <div className="row" style={{ marginTop: 12 }}><button className="btn" onClick={start} disabled={!!t.busy}>Rebuild and compare</button></div>
          {job && <div style={{ marginTop: 12 }}><JobLine job={job} label="Rebuild" /><Events job={job} /></div>}
        </div>
        {st && (
          <div className="card">
            <span className="label">Staged result</span>
            <h3>{READINESS[st.readiness] || st.readiness}</h3>
            <p className="small">{v?.status === "pass" ? `The ${v.profile.replace("_", " ")} profile passed.` : v?.status === "fail" ? `The ${v.profile.replace("_", " ")} profile failed on ${v.failed?.length || 0} check(s).` : `The comparison is incomplete: some evidence is missing.`}</p>
            {v?.failed?.length > 0 && <ul className="tight small">{v.failed.slice(0, 8).map((f: string) => <li key={f}>{f.replace("regions.", "region ").replace("geometry.", "position of ").replace("color.", "colour ")}</li>)}</ul>}
            {v?.blocking_unknowns?.length > 0 && <p className="small muted">Unknown: {v.blocking_unknowns.slice(0, 5).join("; ")}</p>}
            <p className="small">Fresh-process re-render: {st.reproducibility?.status === "pass" ? "identical (0 px differ)" : st.reproducibility?.status === "fail" ? <strong className="bad">differs by {st.reproducibility.unequal_pixels} px — kept as evidence; no exact claim</strong> : "not checked"}</p>
            <p className="small muted">Exact pixel identity requires zero differing decoded pixels. A partial rebuild can still be saved and used with its limitations shown.</p>
            <div className="row"><button className="btn" onClick={next}>Review and save →</button></div>
            <Dev data={st} />
          </div>
        )}
      </div>
    </div>
  );
}

function Save({ t, reload }: { t: Template; reload: () => void }) {
  const nav = useNavigate();
  const [note, setNote] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const toast = useToast();
  const st = t.draft?.staged;
  const job = useJob(jobId, (j) => { reload(); if (j.status === "completed") { toast("Saved to the library"); nav(`/templates/${t.id}`); } });
  const accept = async () => { try { const j = await api.post<any>(`/api/templates/${t.id}/accept`, { stage_id: st.stage_id, note }); setJobId(j.id); } catch (e) { toast(errText(e), true); } };
  const saveDraftVersion = async () => { try { const j = await api.post<any>(`/api/templates/${t.id}/save-version`, { note }); setJobId(j.id); } catch (e) { toast(errText(e), true); } };
  return (
    <div className="grid2">
      <div className="card">
        <h3>Accept the reviewed rebuild</h3>
        {st ? <>
          <p>Saves an immutable version at <strong>{READINESS[st.readiness] || st.readiness}</strong>, with the staged baseline, renderer pin and comparison evidence. Its limitations stay visible wherever it is used.</p>
          <label className="field"><span className="label">Note (optional)</span><input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. headline font is a close candidate" /></label>
          <button className="btn accent" onClick={accept} disabled={!!jobId && job?.status === "running"}>Accept and save to library</button>
        </> : <p className="muted">No staged rebuild yet. Rebuild and compare first, or save the draft as it is.</p>}
      </div>
      <div className="card">
        <h3>Save partial work</h3>
        <p className="small">Saves the draft as a version without an accepted rebuild ({READINESS[t.readiness] || t.readiness}). It can be inspected and used for creative generation, but not for editable adaptation, which needs an approved baseline.</p>
        <button className="btn secondary" onClick={saveDraftVersion}>Save draft as a version</button>
      </div>
      {job && <div className="card" style={{ gridColumn: "1 / -1" }}><JobLine job={job} label="Saving version" /><Events job={job} /></div>}
    </div>
  );
}
