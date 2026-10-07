// Copy editor: visual selection, inspector controls and a command field. Every request is compiled to typed operations
// and previewed (scope, dependencies, lock and constraint conflicts) before it is applied as one verified transaction.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Template } from "../api";
import ElementCanvas, { type El } from "../components/ElementCanvas";
import { Dev, errText, Events, JobLine, useJob, useToast } from "../lib";

type Design = { head: number; revisions: number[]; history: any[]; baseline_revision: number; scene: any; edits: any[]; unsaved: boolean };
type Compiled = { ops: any[]; compiled_by: string; explanation?: string; base_revision: number; scope: { ok: boolean; changes?: any[]; conflicts?: any[]; message?: string; relaxed?: any[]; warnings?: string[] } };

export default function CopyEditor() {
  const { id } = useParams();
  const [t, setT] = useState<Template | null>(null);
  const [d, setD] = useState<Design | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [keep, setKeep] = useState(true);
  const [comp, setComp] = useState<Compiled | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [imgOk, setImgOk] = useState(true);
  const [note, setNote] = useState("");
  const toast = useToast();
  const load = async () => {
    try {
      const x = await api.get<Template>(`/api/templates/${id}`);
      setT(x);
      if (x.design_variant) setD(await api.get<Design>(`/api/templates/${id}/design`));
    } catch (e) { toast(errText(e), true); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const job = useJob(jobId, (j) => { setComp(null); load(); setImgOk(true); if (j.status === "completed") toast(j.kind === "template.save_version" ? "Saved as a new version" : "Done"); });
  if (!t) return <p className="muted">Loading…</p>;
  if (t.role !== "copy") return <div className="notice">Original templates are read-only. <Link to={`/templates/${t.id}`}>Make a copy</Link> to change it.</div>;
  if (!d) return <div className="stack"><p className="muted">Preparing the copy…</p>{t.busy && <JobLine job={job} />}</div>;
  const s = d.scene;
  const nodes: any[] = s.nodes;
  const els: El[] = nodes.filter((n) => n.type !== "background" && n.type !== "group").map((n) => ({ key: n.id, type: (n.role === "logo" ? "logo" : n.type === "path" ? "shape" : n.type) as El["type"],
    role: n.alias || n.role, bbox: [n.geometry.x, n.geometry.y, n.geometry.w, n.geometry.h], status: n.visible === false ? "rejected" : "accepted" }));
  const node = nodes.find((n) => n.id === sel);
  const compile = async (body: any) => {
    try { setComp(await api.post<Compiled>(`/api/templates/${t.id}/compile`, { keep, ...body })); } catch (e) { toast(errText(e), true); }
  };
  const apply = async () => {
    if (!comp) return;
    try { const j = await api.post<any>(`/api/templates/${t.id}/edit`, { ops: comp.ops, base_revision: comp.base_revision, intent: text || comp.compiled_by, keep }); setJobId(j.id); }
    catch (e) { toast(errText(e), true); }
  };
  const tokens = Object.entries(s.tokens || {}).filter(([, v]: any) => v.type === "color" && typeof v.value === "string") as [string, any][];
  return (
    <>
      <div className="page-head">
        <div><span className="label">Copy editor · revision {d.head}</span><h1>{t.name}</h1>
          <p className="lede">Change supported properties of this copy. The original stays untouched; every saved edit becomes a revision, verified in the pinned renderer.</p></div>
        <div className="row">
          {d.unsaved && <span className="tag warn">unsaved revisions</span>}
          <button className="btn secondary" disabled={d.head === d.baseline_revision} onClick={async () => { try { const j = await api.post<any>(`/api/templates/${t.id}/undo`); setJobId(j.id); } catch (e) { toast(errText(e), true); } }}>Undo last edit</button>
          <Link className="btn ghost" to={`/templates/${t.id}`}>Template page</Link>
        </div>
      </div>
      {job && <div className="card flat" style={{ marginBottom: 14 }}><JobLine job={job} label={job.kind.replace("template.", "")} /><Events job={job} /></div>}
      <div className="split">
        <div className="stack">
          <div className="seg" role="group" aria-label="View"><button aria-pressed={!sel} onClick={() => setSel(null)}>Current render</button><button aria-pressed={!!sel} onClick={() => setSel(els[0]?.key || null)}>Select elements</button></div>
          {!sel ? (
            imgOk ? <div className="viewer"><img src={`/api/templates/${t.id}/head.png?rev=${d.head}`} alt={`Render of revision ${d.head}`} onError={() => setImgOk(false)} /></div>
              : <div className="empty"><p>Revision {d.head} has no render yet.</p><button className="btn" onClick={async () => { const j = await api.post<any>(`/api/templates/${t.id}/render-head`); setJobId(j.id); }}>Render current state</button></div>
          ) : (
            <ElementCanvas src={`/api/templates/${t.id}/files/work/source/canonical.png`} width={s.canvas.width} height={s.canvas.height} elements={els} selected={sel} onSelect={setSel} readOnly />
          )}
          <div className="card flat">
            <span className="label">History</span>
            <ul className="tight small">{d.edits.slice().reverse().slice(0, 12).map((e, i) => <li key={i}>{e.restored_version !== undefined ? `restored version ${e.restored_version} as version ${e.new_version}` : e.undo_to !== undefined ? `undo → revision ${e.undo_to}` : `rev ${e.revision}: ${e.intent} · ${e.verification}${e.outside_influence !== undefined && e.outside_influence !== null ? ` · ${e.outside_influence} px outside influence` : ""}`}</li>)}</ul>
            {!d.edits.length && <p className="small muted">No edits yet.</p>}
            <div className="row" style={{ marginTop: 8 }}>
              <input type="text" placeholder="Version note (optional)" value={note} onChange={(e) => setNote(e.target.value)} style={{ maxWidth: 280 }} aria-label="Version note" />
              <button className="btn" disabled={!d.unsaved} onClick={async () => { try { const j = await api.post<any>(`/api/templates/${t.id}/save-version`, { note }); setJobId(j.id); } catch (e) { toast(errText(e), true); } }}>Save as new version</button>
            </div>
          </div>
        </div>
        <div className="stack sticky">
          <div className="card">
            <span className="label">Describe a change</span>
            <form className="stack" onSubmit={(e) => { e.preventDefault(); compile({ text }); }}>
              <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. move the headline up 12px · make the accent #2E5A44 · lock layout" aria-label="Change request" />
              <div className="row between"><label className="check small"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> Keep everything else</label>
                <button className="btn secondary small" type="submit" disabled={!text.trim()}>Preview scope</button></div>
            </form>
          </div>
          {node && (
            <div className="card">
              <div className="row between"><strong>{node.alias || node.id}</strong><span className="tag">{node.type}</span></div>
              {node.type === "text" && <TextControl node={node} onCompile={compile} />}
              <MoveControl node={node} onCompile={compile} />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn ghost small" onClick={() => compile({ ops: [{ op: "set", path: `${node.id}.visible`, value: node.visible === false }] })}>{node.visible === false ? "Show" : "Hide"}</button>
                <button className="btn ghost small" onClick={() => compile({ ops: [{ op: "lock", target: node.id, hard: true }] })}>Lock</button>
                {(s.locks || []).some((l: any) => l.target === node.id) && <button className="btn ghost small" onClick={() => compile({ ops: [{ op: "unlock", target: node.id }] })}>Unlock</button>}
              </div>
            </div>
          )}
          <div className="card">
            <span className="label">Palette</span>
            {tokens.map(([k, v]) => <ColorRow key={k} name={k} value={v.value} onCompile={compile} />)}
            {(s.locks || []).length > 0 && <p className="small muted">Locks: {s.locks.map((l: any) => `${l.target}${l.hard ? "" : " (soft)"}`).join(", ")}</p>}
          </div>
          {comp && (
            <div className={`card ${comp.scope.ok ? "" : "flat"}`}>
              <span className="label">Preview of this change · {comp.compiled_by}</span>
              <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>{comp.ops.map((o) => JSON.stringify(o)).join("\n")}</pre>
              {comp.explanation && <p className="small">{comp.explanation}</p>}
              {comp.scope.ok ? (
                <>
                  <p className="small">Changes {comp.scope.changes?.length} property path(s); everything else is {keep ? "frozen and verified" : "unchanged unless a dependency"}.</p>
                  <ul className="tight small">{comp.scope.changes?.slice(0, 10).map((c, i) => <li key={i}><code>{c.path}</code> <span className="muted">{c.kind}{c.why ? ` — ${c.why}` : ""}</span></li>)}</ul>
                  {comp.scope.relaxed && comp.scope.relaxed.length > 0 && <p className="small notice warn">Relaxes {comp.scope.relaxed.length} measured relationship(s).</p>}
                  <div className="row"><button className="btn accent" onClick={apply}>Apply as a new revision</button><button className="btn ghost" onClick={() => setComp(null)}>Discard</button></div>
                </>
              ) : (
                <div className="notice bad small"><strong>Nothing would be committed.</strong> {comp.scope.message}
                  <ul className="tight">{comp.scope.conflicts?.map((c: any, i: number) => <li key={i}>{c.message || c.resolve || c.problem || JSON.stringify(c).slice(0, 160)}{c.resolve ? ` — ${c.resolve}` : ""}</li>)}</ul></div>
              )}
              <Dev data={comp} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function TextControl({ node, onCompile }: { node: any; onCompile: (b: any) => void }) {
  const [v, setV] = useState(node.content || "");
  useEffect(() => setV(node.content || ""), [node.id, node.content]);
  return (
    <div className="field" style={{ marginTop: 8 }}>
      <span className="label">Text</span>
      <textarea rows={2} value={v} onChange={(e) => setV(e.target.value)} dir="auto" />
      <button className="btn secondary small" disabled={v === node.content} onClick={() => onCompile({ ops: [{ op: "set", path: `${node.id}.content`, value: v }] })}>Preview text change</button>
    </div>
  );
}

function MoveControl({ node, onCompile }: { node: any; onCompile: (b: any) => void }) {
  const [dx, setDx] = useState(0), [dy, setDy] = useState(0);
  return (
    <div className="row small" style={{ marginTop: 8 }}>
      <span className="label">Move</span>
      <label className="row" style={{ gap: 4 }}>x<input type="number" style={{ width: 70 }} value={dx} onChange={(e) => setDx(+e.target.value)} /></label>
      <label className="row" style={{ gap: 4 }}>y<input type="number" style={{ width: 70 }} value={dy} onChange={(e) => setDy(+e.target.value)} /></label>
      <button className="btn secondary small" disabled={!dx && !dy} onClick={() => onCompile({ ops: [{ op: "move", node: node.id, dx, dy }] })}>Preview move</button>
    </div>
  );
}

function ColorRow({ name, value, onCompile }: { name: string; value: string; onCompile: (b: any) => void }) {
  const [v, setV] = useState(value.slice(0, 7));
  useEffect(() => setV(value.slice(0, 7)), [value]);
  return (
    <div className="palette-row">
      <input type="color" value={v} onChange={(e) => setV(e.target.value)} aria-label={`${name} colour`} style={{ width: 44, height: 36, border: 0, background: "none" }} />
      <div style={{ flex: 1 }}><strong className="small">{name}</strong> <span className="mono">{value}</span></div>
      <button className="btn secondary small" disabled={v.toLowerCase() === value.slice(0, 7).toLowerCase()} onClick={() => onCompile({ ops: [{ op: "set", path: `tokens.${name}`, value: v.toUpperCase() }] })}>Preview</button>
    </div>
  );
}
