// Template inspector: plain-language explanations first; ids, hashes and raw records stay in developer views.
import { useMemo, useState } from "react";
import type { Template, Version } from "../api";
import { Dev, StatusDot } from "../lib";
import ElementCanvas, { type El } from "./ElementCanvas";

export type ModelView = {
  scene: any; assets: Record<string, any>; passport: any; evidence: any[]; artifacts: any; constants: { categories: string[]; facets: Record<string, string[]> };
  migrations: any[]; source: string;
};

const TABS = ["Overview", "Elements", "Colours", "Typography", "Image", "Depth & surface", "Slots", "Rules", "Evidence", "Versions"] as const;
const STATUS_HELP: Record<string, string> = { measured: "measured by a tool", observed: "observed / confirmed", inferred: "inferred (hypothesis)",
  unknown: "unknown", not_applicable: "not applicable" };

function Claim({ label, c }: { label: string; c: any }) {
  if (!c) return null;
  const v = c.value ?? null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{v === null || v === "" ? <span className="muted">unknown</span> : String(Array.isArray(v) ? v.join(", ") : v)}
        {c.status && <span className="tag" style={{ marginLeft: 8 }}>{c.status.replace("_", " ")}</span>}</dd>
    </>
  );
}

function Coverage({ m }: { m: ModelView }) {
  const cov = m.scene.scan?.coverage || {};
  const counts: Record<string, number> = {};
  m.constants.categories.forEach((c) => { const st = cov[c]?.status || "missing"; counts[st] = (counts[st] || 0) + 1; });
  return (
    <details>
      <summary className="small" style={{ cursor: "pointer" }}>{m.constants.categories.length} categories · {Object.entries(counts).map(([k, v]) => `${v} ${STATUS_HELP[k] || k}`).join(" · ")} — show details</summary>
    <table className="data">
      <thead><tr><th>Category</th><th>Finding</th><th>Status</th></tr></thead>
      <tbody>
        {m.constants.categories.map((cat) => {
          const e = cov[cat];
          return (
            <tr key={cat}>
              <td><strong>{cat.replace(/_/g, " ")}</strong>
                {e?.facets && <ul className="tight small muted">{Object.entries(e.facets).map(([k, f]: any) => <li key={k}>{k.replace(/_/g, " ")}: {f.status}{f.note ? ` — ${f.note}` : ""}</li>)}</ul>}</td>
              <td className="small">{e ? e.note : <span className="tag bad">missing</span>}{e?.ambiguity?.length ? <div className="muted">Unresolved: {e.ambiguity.join("; ")}</div> : null}</td>
              <td><span className="row" style={{ gap: 6 }}><StatusDot status={!e ? "error" : e.status === "unknown" ? "warning" : e.status === "inferred" ? "" : "pass"} />{e ? STATUS_HELP[e.status] || e.status : "missing"}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </details>
  );
}

function chain(m: any) {
  return (m.chain || []).map((s: string, i: number) => <span key={i}>{i > 0 && <span className="muted"> → </span>}{s}</span>);
}

export default function Inspector({ t, m, fileUrl, versions, onRestore, onCopy, canRestore }: {
  t: Template; m: ModelView; fileUrl: (rel: string) => string; versions?: Version[]; onRestore?: (v: Version) => void; onCopy?: (v: Version) => void; canRestore?: boolean;
}) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [sel, setSel] = useState<string | null>(null);
  const s = m.scene, pp = m.passport || {};
  const nodes: any[] = s.nodes || [];
  const els: El[] = useMemo(() => nodes.filter((n) => n.geometry && n.type !== "background" && n.type !== "group").map((n) => ({
    key: n.id, type: (n.type === "path" ? "shape" : n.role === "logo" ? "logo" : n.type) as El["type"], role: n.alias || n.role,
    bbox: [n.geometry.x, n.geometry.y, n.geometry.w, n.geometry.h], status: "accepted" })), [nodes]);
  const selNode = nodes.find((n) => n.id === sel);
  const evById = Object.fromEntries((m.evidence || []).map((e: any) => [e.evidence_id, e]));
  const com = s.communication || {};
  const W = s.canvas?.width, H = s.canvas?.height;
  return (
    <div>
      <div className="tabs" role="tablist" aria-label="Inspector">
        {TABS.map((x) => <button key={x} role="tab" aria-selected={tab === x} onClick={() => setTab(x)}>{x}</button>)}
      </div>
      {tab === "Overview" && (
        <div className="stack">
          <dl className="kv">
            <Claim label="Character" c={pp.character} /><Claim label="Theme" c={pp.theme} /><Claim label="Goal" c={pp.goal || com.goal} />
            <Claim label="Message" c={pp.literal_message || com.literal_message} /><Claim label="Takeaway" c={pp.takeaway || com.takeaway} />
            <Claim label="How it delivers it" c={pp.mechanism} /><Claim label="Use it for" c={pp.usage} /><Claim label="Not for" c={pp.unsuitable_for} />
            <Claim label="Channels" c={pp.channels} />
            <dt>Canvas</dt><dd>{W} × {H} px · {t.aspect_ratio}</dd>
          </dl>
          {com.mechanisms?.length > 0 && (
            <div><span className="label">How the design works (hypotheses)</span>
              <ul className="tight small">{com.mechanisms.map((x: any, i: number) => <li key={i}>{chain(x)} <span className="tag">{x.status}/{x.confidence}</span>
                {x.competing?.length ? <div className="muted">Other readings: {x.competing.join("; ")}</div> : null}</li>)}</ul>
              <p className="small muted">visible choice → likely attention or association → intended takeaway → intended action. Interpretations, not measured conversions or designer intent.</p></div>
          )}
          {pp.unresolved?.length > 0 && <div className="notice warn"><strong>Limitations</strong><ul className="tight small">{pp.unresolved.map((u: string) => <li key={u}>{u.replace(/^not promoted: /, "Not promoted to a higher readiness: ")}</li>)}</ul></div>}
          <div><span className="label">Scan coverage</span><Coverage m={m} /></div>
        </div>
      )}
      {tab === "Elements" && (
        <div className="split">
          <ElementCanvas src={fileUrl("source/canonical.png")} width={W} height={H} elements={els} selected={sel} onSelect={setSel} readOnly />
          <div className="stack">
            {!selNode ? <p className="muted">Select an element to see its measured position, role and evidence.</p> : (
              <div className="card flat">
                <h3>{selNode.alias || selNode.id} <span className="tag">{selNode.type}</span></h3>
                <dl className="kv small">
                  <dt>Role</dt><dd>{selNode.role}</dd>
                  <dt>Box</dt><dd className="mono">x {Math.round(selNode.geometry.x)} · y {Math.round(selNode.geometry.y)} · {Math.round(selNode.geometry.w)} × {Math.round(selNode.geometry.h)}</dd>
                  {selNode.content && <><dt>Text</dt><dd style={{ whiteSpace: "pre-wrap" }}>{selNode.content}</dd></>}
                  {selNode.radius ? <><dt>Corner radius</dt><dd>{selNode.radius}px</dd></> : null}
                  <dt>Editable as</dt><dd>{selNode.editability || "live"}</dd>
                </dl>
                {selNode.provenance && <><span className="label">Where each value comes from</span>
                  <ul className="tight small">{Object.entries(selNode.provenance).map(([k, p]: any) => <li key={k}><strong>{k}</strong>: {STATUS_HELP[p.status] || p.status} ({p.confidence}){p.note ? ` — ${p.note}` : ""}</li>)}</ul></>}
                <Dev data={selNode} />
              </div>
            )}
            <table className="data"><thead><tr><th>Element</th><th>Type</th><th>Role</th></tr></thead>
              <tbody>{nodes.map((n) => <tr key={n.id} onClick={() => setSel(n.id)} style={{ cursor: "pointer", background: sel === n.id ? "var(--paper-2)" : undefined }}>
                <td><button className="btn ghost small" onClick={() => setSel(n.id)}>{n.alias || n.id}</button></td><td>{n.type}</td><td>{n.role}</td></tr>)}</tbody></table>
            {s.communication?.hierarchy?.order?.length > 0 && <p className="small">Likely reading order ({s.communication.hierarchy.status}): {s.communication.hierarchy.order.join(" → ")}</p>}
          </div>
        </div>
      )}
      {tab === "Colours" && (
        <div className="stack">
          {Object.entries(s.tokens || {}).filter(([, v]: any) => v.type === "color").map(([k, v]: any) => (
            <div key={k} className="palette-row">
              <span className="swatch" style={{ background: typeof v.value === "string" ? v.value : `linear-gradient(90deg, ${(v.value.stops || []).map((x: any) => x.color).join(",")})` }} />
              <div style={{ flex: 1 }}><strong>{k}</strong> <span className="mono">{typeof v.value === "string" ? v.value : "gradient"}</span>
                <div className="small muted">{STATUS_HELP[v.status] || v.status} ({v.confidence}) · {v.sample_method === "ink_core" ? "sampled from text stroke cores" : "median of clean patches"}{v.note ? ` · ${v.note}` : ""}</div>
                <div className="small muted">Used by: {nodes.filter((n) => JSON.stringify([n.fill, n.stroke]).includes(`"${k}"`)).map((n) => n.alias || n.id).join(", ") || "—"}</div></div>
            </div>
          ))}
          {!Object.keys(s.tokens || {}).length && <p className="muted">No colour tokens measured yet.</p>}
        </div>
      )}
      {tab === "Typography" && (
        <div className="stack">
          {nodes.filter((n) => n.type === "text").map((n) => {
            const f = n.font || {}, a = m.assets[f.asset] || {};
            return (
              <div key={n.id} className="card flat">
                <h4>{n.alias || n.id} <span className="muted small">“{(n.content || "").slice(0, 60)}”</span></h4>
                <dl className="kv small">
                  <dt>Render font</dt><dd>{a.font_names?.full || f.family || "—"} <span className="tag">{f.identity?.status === "verified" ? "identity verified" : "candidate — identity unknown"}</span></dd>
                  <dt>Size / line</dt><dd>{f.size}px / {n.line_height}px · weight {f.weight}</dd>
                  <dt>Tracking</dt><dd>{n.tracking || 0}px</dd><dt>Baseline</dt><dd>{n.first_baseline}px</dd>
                  <dt>Align / dir</dt><dd>{n.align} · {n.direction || "ltr"}{n.lang ? ` · ${n.lang}` : ""}</dd>
                  <dt>Fit</dt><dd>{n.fit?.policy === "fit" ? `may shrink to ${n.fit.min_size}px` : "strict (never shrunk or clipped)"} · max {n.fit?.max_lines || "?"} line(s)</dd>
                  {f.identity?.candidates?.length > 0 && <><dt>Candidates</dt><dd>{f.identity.candidates.slice(0, 4).map((c: any) => `${c.full}${c.iou !== undefined ? ` (IoU ${c.iou})` : ""}`).join(", ")}</dd></>}
                </dl>
              </div>
            );
          })}
          {!nodes.some((n) => n.type === "text") && <p className="muted">No text elements.</p>}
        </div>
      )}
      {tab === "Image" && (
        <div className="stack">
          {nodes.filter((n) => n.type === "image" || (n.type === "background" && n.asset)).map((n) => {
            const a = m.assets[n.asset] || {};
            return (
              <div key={n.id} className="card flat">
                <h4>{n.alias || n.id}</h4>
                <dl className="kv small">
                  <dt>Source</dt><dd>{a.source === "reference_crop" ? "bounded crop of the reference (original photo unavailable)" : a.source}</dd>
                  <dt>Placement</dt><dd>{n.placement?.fit}{n.placement?.focal ? ` · focal ${n.placement.focal.join(", ")}` : ""}</dd>
                  <dt>Mask</dt><dd>{n.mask ? `${n.mask.type}${n.mask.radius ? ` r${n.mask.radius}` : ""}` : "none"}</dd>
                  <dt>Treatment</dt><dd>{(n.treatment || []).map((x: any) => x.op).join(" → ") || "none recorded"}</dd>
                  <dt>Shadows</dt><dd>{(n.effects || []).filter((x: any) => x.type === "drop_shadow").length ? "live drop shadow" : "none"}{a.baked_effects?.length ? ` · baked: ${a.baked_effects.join(", ")}` : ""}</dd>
                  <dt>Replace with</dt><dd>{(s.slots || []).some((x: any) => x.node === n.id) ? "a product photo (same frame, crop intent, mask and treatment)" : "not a slot"}</dd>
                </dl>
              </div>
            );
          })}
          {!nodes.some((n) => n.type === "image" || (n.type === "background" && n.asset)) && <p className="muted">No image regions.</p>}
        </div>
      )}
      {tab === "Depth & surface" && (
        <div className="stack">
          <p className="small">Paint order (back → front): {nodes.map((n) => n.alias || n.id).join(" → ")}</p>
          {["depth_compositing", "surface_texture", "lighting"].map((k) => {
            const e = s.scan?.coverage?.[k];
            return <div key={k}><span className="label">{k.replace(/_/g, " ")}</span><p className="small">{e ? `${e.note} (${STATUS_HELP[e.status] || e.status})` : "not assessed"}</p></div>;
          })}
        </div>
      )}
      {tab === "Slots" && (
        <table className="data">
          <thead><tr><th>Slot</th><th>Type</th><th>Rules</th><th>Editable</th></tr></thead>
          <tbody>{(s.slots || []).map((x: any) => {
            const n = nodes.find((y) => y.id === x.node);
            return <tr key={x.id}><td><strong>{x.role}</strong><div className="small muted">{n?.content ? `“${n.content.slice(0, 50)}”` : x.node}</div></td><td>{x.type}</td>
              <td className="small">{x.limits?.required ? "required" : "optional"}{x.limits?.max_chars ? ` · ≤ ${x.limits.max_chars} chars` : ""}{x.limits?.max_lines ? ` · ≤ ${x.limits.max_lines} line(s)` : ""} · fit {n?.fit?.policy || x.fit}</td>
              <td className="small">{(pp.editability_coverage?.slots || {})[x.id] || "—"}</td></tr>;
          })}</tbody>
        </table>
      )}
      {tab === "Rules" && (
        <div className="stack">
          <div><span className="label">Locks</span>
            {(s.locks || []).length ? <ul className="tight small">{s.locks.map((l: any) => <li key={l.id}>{l.hard ? "Hard" : "Soft"} {l.kind} lock on <strong>{l.target}</strong>{l.box ? ` [${l.box.join(", ")}]` : ""}</li>)}</ul>
              : <p className="small muted">No locks: every property may change when explicitly requested.</p>}</div>
          <div><span className="label">Measured relationships</span>
            {(s.constraints || []).length ? <ul className="tight small">{s.constraints.map((c: any) => <li key={c.id}>{c.type}: {c.a} ↔ {c.b} {c.relaxable ? "(relaxable)" : "(required)"}</li>)}</ul>
              : <p className="small muted">None declared.</p>}</div>
          {t.draft?.default_instructions && <div><span className="label">Default instructions</span><p className="small">{t.draft.default_instructions}</p></div>}
          {(pp.preserve || t.passport?.preserve) && <div><span className="label">Preserve</span><p className="small">{String((t.passport?.preserve as any)?.value || "")}</p></div>}
          <p className="small muted">Compatible changes: copy in text slots, product photos in image slots, colour tokens, and typed edits on a copy. Everything else is preserved and verified against the approved baseline.</p>
        </div>
      )}
      {tab === "Evidence" && (
        <div className="stack">
          <p className="small muted">{(m.evidence || []).length} evidence records. Each finding points at the record that produced it.</p>
          <table className="data"><thead><tr><th>Record</th><th>Method</th><th>Status</th><th>Why</th></tr></thead>
            <tbody>{(m.evidence || []).map((e: any) => <tr key={e.evidence_id}><td className="mono">{e.evidence_id}<div className="muted">{e.object || ""}</div></td>
              <td className="small">{e.method.replace(/_/g, " ")}<div className="muted mono">{(e.tool || "").slice(0, 60)}</div></td><td className="small">{e.status} / {e.confidence}</td>
              <td className="small">{e.justification}{e.limitations?.length ? <div className="muted">Limits: {e.limitations.join("; ")}</div> : null}
                {e.artifacts?.filter((a: string) => a.endsWith(".png")).slice(0, 1).map((a: string) => <div key={a}><a href={fileUrl(a)} target="_blank" rel="noreferrer">view artifact</a></div>)}</td></tr>)}</tbody></table>
          <Dev data={{ evidence_index: Object.keys(evById).length }} />
        </div>
      )}
      {tab === "Versions" && (
        <div className="stack">
          {(versions || []).length === 0 && <p className="muted">No saved versions yet.</p>}
          {(versions || []).map((v) => (
            <div key={v.id} className="card flat row between">
              <div><strong>Version {v.number}</strong> <span className="tag">{v.readiness_label}</span> <span className="muted small">{v.created_from.replace(/_/g, " ")} · {new Date(v.created_at).toLocaleString()}</span>
                {v.acceptance?.note && <div className="small">“{v.acceptance.note}”</div>}
                {v.acceptance?.restored_from && <div className="small muted">restored from version {v.acceptance.number}</div>}
                <Dev data={{ bundle_sha256: v.bundle_sha256, scene_sha256: v.scene_sha256, baseline: v.baseline, acceptance: v.acceptance }} label="Hashes and baseline" /></div>
              <div className="row">
                <a className="btn secondary small" href={v.download_url}>Export bundle</a>
                {onCopy && <button className="btn secondary small" onClick={() => onCopy(v)}>Copy this version</button>}
                {canRestore && onRestore && t.current_version?.id !== v.id && <button className="btn secondary small" onClick={() => onRestore(v)}>Restore as new version</button>}
              </div>
            </div>
          ))}
          {m.migrations?.length > 0 && <div><span className="label">Renderer migrations</span><ul className="tight small">{m.migrations.map((x: any, i: number) =>
            <li key={i}>{x.from?.channel} {x.from?.browser_version} → {x.to?.channel} {x.to?.browser_version}: {x.vs_previous_baseline?.unequal_pixels} px differed (preview {x.preview_id || "—"})</li>)}</ul></div>}
        </div>
      )}
    </div>
  );
}
