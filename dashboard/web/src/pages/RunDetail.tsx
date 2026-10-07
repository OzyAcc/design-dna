// Run review: gallery + per-output detail with the actual render, the text used, checks and limitations.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download, MODES, type Output } from "../api";
import { Dev, errText, Events, fmtBytes, newKey, STATUS_LABEL, StatusDot, useToast } from "../lib";

type RunRes = { id: string; name: string; status: string; counts: Record<string, number>; outputs: Output[]; created_at: string };

function latest(outs: Output[]) {
  const by: Record<string, Output> = {};
  for (const o of outs) if (!by[o.pair_id] || o.revision > by[o.pair_id].revision) by[o.pair_id] = o;
  return Object.values(by);
}

export default function RunDetail() {
  const { id } = useParams();
  const [r, setR] = useState<RunRes | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const toast = useToast();
  const load = () => api.get<RunRes>(`/api/runs/${id}`).then((x) => { setR(x); setErr(""); }).catch((e) => setErr(errText(e)));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (r?.status === "running") { const t = setTimeout(load, 1500); return () => clearTimeout(t); } }, [r]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="notice bad">{err}</div>;
  if (!r) return <p className="muted">Loading…</p>;
  const outs = latest(r.outputs);
  const zip = async (ids?: string[]) => { try { await download(`/api/runs/${r.id}/zip`, { output_ids: ids }, "design-dna-outputs.zip"); } catch (e) { toast(errText(e), true); } };
  return (
    <>
      <div className="page-head">
        <div><span className="label">Run · {new Date(r.created_at).toLocaleString()}</span><h1>{r.name}</h1>
          <div className="row"><StatusDot status={r.status} /><span>{STATUS_LABEL[r.status] || r.status}</span>
            <span className="muted small">{Object.entries(r.counts).map(([k, v]) => `${v} ${STATUS_LABEL[k]?.toLowerCase() || k}`).join(" · ")}</span></div></div>
        <div className="row">
          {r.status === "running" && <button className="btn secondary" onClick={async () => { await api.post(`/api/runs/${r.id}/cancel`); toast("Cancelling — finished files are kept"); load(); }}>Cancel remaining</button>}
          <button className="btn secondary" disabled={!sel.length} onClick={() => zip(sel)}>Download selected ({sel.length})</button>
          <button className="btn" disabled={!outs.some((o) => o.status === "completed")} onClick={() => zip()}>Download batch ZIP</button>
        </div>
      </div>
      <div className="gallery">
        {outs.map((o) => {
          const png = o.files.find((f) => f.kind === "png") || o.files.find((f) => f.kind === "refused_candidate");
          return (
            <article key={o.id} className="gal-item">
              <button className="art" style={{ border: 0, padding: 0, cursor: "pointer" }} onClick={() => setOpen(o.id)} aria-label={`Open ${o.inputs?.product?.name} on ${o.inputs?.template?.name}`}>
                {png ? <img src={png.url} alt="" /> : <span className="muted small">{o.status === "running" || o.status === "queued" ? <><span className="spinner" /> {STATUS_LABEL[o.status]}</> : "no image"}</span>}
              </button>
              <div className="body">
                <div className="row between"><strong>{o.inputs?.product?.name}</strong><label className="check small"><input type="checkbox" checked={sel.includes(o.id)} disabled={o.status !== "completed"} onChange={(e) => setSel((x) => e.target.checked ? [...x, o.id] : x.filter((y) => y !== o.id))} aria-label="Select for download" /></label></div>
                <span className="muted">{o.inputs?.template?.name} v{o.inputs?.template?.number} · {o.language} · {MODES[o.mode]}</span>
                <span className="row" style={{ gap: 6 }}><StatusDot status={o.status} />{STATUS_LABEL[o.status] || o.status}{o.revision > 1 ? ` · revision ${o.revision}` : ""}
                  {o.review_state !== "unreviewed" && <span className={`tag ${o.review_state === "approved" ? "ok" : "bad"}`}>{o.review_state}</span>}</span>
                <button className="btn secondary small" onClick={() => setOpen(o.id)}>Review</button>
              </div>
            </article>
          );
        })}
      </div>
      {open && <OutputDrawer id={open} onClose={() => setOpen(null)} onChanged={load} onOpen={setOpen} />}
    </>
  );
}

function Checks({ o }: { o: Output }) {
  const c = o.checks || {};
  if (c.path === "creative") return (
    <dl className="kv small">
      <dt>Path</dt><dd>Creative reference generation</dd>
      <dt>Provider</dt><dd>{o.provenance?.provider?.provider} {o.provenance?.provider?.model}{o.provenance?.mock ? " (MOCK — test only)" : ""}</dd>
      <dt>Request id</dt><dd className="mono">{o.provenance?.provider?.request_id || "—"}</dd>
      <dt>Size</dt><dd>requested {c.dimensions?.requested}, returned {c.dimensions?.returned?.join("×")} (template {c.dimensions?.template?.join("×")})</dd>
      <dt>Preservation</dt><dd>{c.preservation}</dd><dt>Editability</dt><dd>{c.editability}</dd>
    </dl>
  );
  if (!c.path) return <p className="small muted">No checks ran.</p>;
  const vs = c.visual_changes || {};
  return (
    <dl className="kv small">
      <dt>Verification</dt><dd><StatusDot status={c.verification_status} /> {c.verification_status?.replace(/_/g, " ")}</dd>
      <dt>Model changes</dt><dd>{c.model_changes?.status === "pass" ? `only the requested properties changed (${c.model_changes.requested?.length}); ${c.model_changes.frozen_leaf_paths ?? "—"} others frozen and verified` : `unexplained changes: ${(c.model_changes?.unexplained || []).join(", ")}`}</dd>
      <dt>Pixels outside the edit</dt><dd>{vs.status === "not_applicable" ? "not applicable (whole-canvas change)" : `${vs.outside_influence ?? "—"} changed (must be 0) · compared against ${vs.compared_against || "—"}`}</dd>
      <dt>Approved baseline</dt><dd>{c.approved_baseline_reproduced === true ? "re-render reproduced it exactly" : c.approved_baseline_reproduced === false ? <strong>did not reproduce — needs review</strong> : "—"}</dd>
      <dt>Requested edits</dt><dd><ul className="tight">{(c.requested_edits || []).map((e: any) => <li key={e.path}><StatusDot status={e.status} /> {e.path.replace("nodes.", "")} — {e.probe}</li>)}</ul></dd>
      {c.pixel_locks?.length > 0 && <><dt>Pixel locks</dt><dd>{c.pixel_locks.map((l: any) => `${l.lock}: ${l.changed_pixels} px`).join(", ")}</dd></>}
      <dt>SVG export</dt><dd>{c.svg?.roundtrip ? `round trip ${c.svg.roundtrip}` : "not exported"}</dd>
      <dt>Renderer</dt><dd>{c.renderer?.status}</dd>
    </dl>
  );
}

function OutputDrawer({ id, onClose, onChanged, onOpen }: { id: string; onClose: () => void; onChanged: () => void; onOpen: (id: string) => void }) {
  const [o, setO] = useState<Output | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const load = () => api.get<Output>(`/api/outputs/${id}`).then((x) => { setO(x); setEdit(Object.fromEntries((x.inputs?.slots || []).map((s: any) => [s.slot_id, s.value ?? ""]))); });
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (o && ["queued", "running"].includes(o.status)) { const t = setTimeout(load, 1500); return () => clearTimeout(t); } }, [o]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!o) return null;
  const png = o.files.find((f) => f.kind === "png");
  const refused = o.files.find((f) => f.kind === "refused_candidate");
  const review = async (state: string) => { try { setO(await api.post<Output>(`/api/outputs/${o.id}/review`, { state })); onChanged(); } catch (e) { toast(errText(e), true); } };
  const retry = async (revise: boolean, confirm = false): Promise<void> => {
    setBusy(true);
    const changed = revise ? Object.fromEntries(Object.entries(edit).filter(([k, v]) => v !== ((o.inputs?.slots || []).find((s: any) => s.slot_id === k)?.value ?? ""))) : undefined;
    try {
      const r = await api.post<any>(`/api/outputs/${o.id}/retry`, { copy: changed, idempotency_key: newKey(), confirm_new_paid_request: confirm });
      toast(`Revision ${r.revision} queued`); onChanged(); onOpen(r.output_id);
    } catch (e: any) {
      if (e.code === "confirm_paid_retry" && window.confirm(`${e.message}\n\nSend a new request anyway?`)) { setBusy(false); return retry(revise, true); }
      toast(errText(e), true);
    } finally { setBusy(false); }
  };
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="od-title" style={{ width: "min(860px, 100vw)" }}>
        <div className="row between"><h2 id="od-title">{o.inputs?.product?.name} × {o.inputs?.template?.name}</h2><button className="btn ghost small" onClick={onClose}>Close</button></div>
        <div className="row small" style={{ marginBottom: 12 }}>
          <StatusDot status={o.status} /> <strong>{STATUS_LABEL[o.status] || o.status}</strong> · revision {o.revision} · template v{o.inputs?.template?.number} · {o.language} · {MODES[o.mode]}
          {(o.revisions || []).length > 1 && <span className="row" style={{ gap: 4 }}>· revisions: {o.revisions!.map((x) => <button key={x.id} className="btn ghost small" aria-pressed={x.id === o.id} onClick={() => onOpen(x.id)}>{x.revision}</button>)}</span>}
        </div>
        <div className="grid2">
          <div className="stack">
            {png ? <div className="viewer"><img className="checker" src={png.url} alt="Final render" /></div>
              : refused ? <div className="stack"><div className="viewer"><img src={refused.url} alt="Refused candidate (not an approved output)" /></div><span className="tag bad">refused candidate — review artifact, not a final output</span></div>
              : <div className="empty"><p className="muted">{["queued", "running"].includes(o.status) ? "Generating…" : "No render was produced."}</p></div>}
            <div className="row">
              {o.files.filter((f) => ["png", "svg", "svg_manifest"].includes(f.kind)).map((f) => <a key={f.url} className="btn secondary small" href={`${f.url}?download=1`}>{f.kind === "svg_manifest" ? "SVG manifest" : f.kind.toUpperCase()} · {fmtBytes(f.bytes)}</a>)}
            </div>
            {o.files.filter((f) => f.kind === "evidence").length > 0 && (
              <details><summary className="small">Comparison evidence</summary>
                {o.files.filter((f) => f.kind === "evidence").map((f) => <figure key={f.url} style={{ margin: "8px 0" }}><figcaption className="label">{f.name.replace("evidence/", "")}</figcaption><img src={f.url} alt={f.name} style={{ width: "100%" }} /></figure>)}
                <p className="small muted">visual_diff: yellow = changed inside the declared influence, red = changed outside it (must be none), blue = influence.</p>
              </details>
            )}
          </div>
          <div className="stack">
            {o.error && <div className={`notice ${o.status === "failed" ? "bad" : "warn"} small`}><strong>{o.error.kind === "conflict" ? "Conflict" : o.error.kind === "provider" ? "Provider" : o.error.kind === "infrastructure" ? "Infrastructure" : "Problem"}:</strong> {o.error.message}
              {o.error.conflicts && <ul className="tight">{o.error.conflicts.slice(0, 6).map((c: any, i: number) => <li key={i}>{c.message || c.problem || c.constraint || c.lock || JSON.stringify(c).slice(0, 140)}{c.detail?.options ? ` — options: ${c.detail.options.join("; ")}` : c.resolve ? ` — ${c.resolve}` : ""}</li>)}</ul>}</div>}
            <div><span className="label">Text used</span>
              {(o.inputs?.slots || []).map((s: any) => <div key={s.slot_id} className="field" style={{ marginBottom: 8 }}>
                <span className="label">{s.role} <span className="slot-src">{s.hidden ? "hidden" : s.source}</span></span>
                {s.locked?.length ? <p className="small">{s.value}</p> : <textarea rows={1} value={edit[s.slot_id] ?? ""} onChange={(e) => setEdit({ ...edit, [s.slot_id]: e.target.value })} dir="auto" />}
              </div>)}
            </div>
            {o.inputs?.instructions?.length > 0 && <div><span className="label">Instructions</span><ul className="tight small">{o.inputs.instructions.map((x: string) => <li key={x}>{x}</li>)}</ul></div>}
            <div><span className="label">Checks</span><Checks o={o} /></div>
            {o.limitations?.length > 0 && <div className="notice warn small"><strong>Limitations</strong><ul className="tight">{o.limitations.map((x) => <li key={x}>{x}</li>)}</ul></div>}
            <div className="row">
              <button className="btn" disabled={o.status !== "completed" || o.review_state === "approved"} onClick={() => review("approved")}>Approve</button>
              <button className="btn secondary" disabled={o.review_state === "rejected"} onClick={() => review("rejected")}>Reject</button>
              {["queued", "running"].includes(o.status) && <button className="btn ghost" onClick={async () => { await api.post(`/api/outputs/${o.id}/cancel`); load(); onChanged(); }}>Cancel</button>}
            </div>
            <div className="row">
              <button className="btn secondary small" disabled={busy || ["queued", "running"].includes(o.status)} onClick={() => retry(false)}>Retry this output</button>
              <button className="btn secondary small" disabled={busy || ["queued", "running"].includes(o.status)} onClick={() => retry(true)}>Regenerate with revised text</button>
            </div>
            <p className="small muted">Retries and regenerations create a new revision; this one is kept. <Link to={`/templates/${o.template_id}`}>Open the template</Link></p>
            <Events job={o.events ? { events: o.events } as any : null} />
            <Dev data={{ id: o.id, pair_id: o.pair_id, checks: o.checks, provenance: o.provenance, provider_requests: o.provider_requests, files: o.files }} />
          </div>
        </div>
      </aside>
    </>
  );
}
