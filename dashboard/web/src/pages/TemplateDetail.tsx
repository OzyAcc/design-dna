// Template detail: large preview + inspector; Use template (shared composer), Copy and edit, Export bundle, Archive.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, READINESS, type Template, type Version } from "../api";
import CompareViewer from "../components/CompareViewer";
import Composer, { useComposer } from "../components/Composer";
import Inspector, { type ModelView } from "../components/Inspector";
import { Dev, errText, Events, JobLine, useJob, useToast } from "../lib";

export default function TemplateDetail() {
  const { id } = useParams();
  const [t, setT] = useState<Template | null>(null);
  const [m, setM] = useState<ModelView | null>(null);
  const [err, setErr] = useState("");
  const [cols, setCols] = useState<{ id: string; name: string }[]>([]);
  const [useOpen, setUseOpen] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mig, setMig] = useState<{ id: string; job: string } | null>(null);
  const c = useComposer();
  const nav = useNavigate();
  const toast = useToast();
  const load = () => api.get<Template>(`/api/templates/${id}`).then((x) => { setT(x); setErr(""); return x; }).catch((e) => { setErr(errText(e)); return null; });
  useEffect(() => {
    load().then((x) => x && api.get<ModelView>(`/api/templates/${id}/model?source=current`).then(setM).catch(() => setM(null)));
    api.get<any[]>("/api/collections").then(setCols).catch(() => {});
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const busyJob = useJob(jobId || t?.busy?.id, () => { setJobId(null); load().then(() => api.get<ModelView>(`/api/templates/${id}/model?source=current`).then(setM).catch(() => {})); });
  const migJob = useJob(mig?.job, () => setMig((x) => x && { ...x }));
  const [migData, setMigData] = useState<any>(null);
  useEffect(() => { if (migJob && ["completed", "needs_review", "failed"].includes(migJob.status) && t) api.get<any[]>(`/api/templates/${t.id}/migrations`).then((ms) => setMigData(ms[0])); }, [migJob?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="notice bad" role="alert">{err}</div>;
  if (!t) return <p className="muted">Loading…</p>;
  const v = t.current_version;
  const src = v ? `v:${v.id}` : "work";
  const fileUrl = (rel: string) => `/api/templates/${t.id}/files/${m?.source?.startsWith("v:") ? m.source : src}/${rel}`;
  const copy = async (ver?: Version) => {
    try { const r = await api.post<{ template: Template }>(`/api/templates/${t.id}/copy`, { version_id: ver?.id }); toast("Copy created"); nav(`/templates/${r.template.id}`); }
    catch (e) { toast(errText(e), true); }
  };
  const act = async (path: string, body: any = {}, msg = "") => { try { const r = await api.post<any>(`/api/templates/${t.id}/${path}`, body); if (r?.id && r.kind) setJobId(r.id); if (msg) toast(msg); load(); } catch (e) { toast(errText(e), true); } };
  const arts = m?.artifacts || {};
  return (
    <>
      <div className="page-head">
        <div>
          <span className="label">{t.role === "copy" ? "Template copy" : "Template"}{v ? ` · version ${v.number}` : " · draft"}</span>
          <h1>{t.name}</h1>
          <div className="row">
            <span className={`tag ${t.readiness === "exact_pixels" || t.readiness === "editable_close" ? "ok" : t.readiness === "partial_baseline" ? "warn" : ""}`}>{READINESS[t.readiness] || t.readiness}</span>
            {t.aspect_ratio && <span className="tag">{t.width} × {t.height} · {t.aspect_ratio}</span>}
            {t.lineage && <span className="small muted">Copy of <Link to={`/templates/${t.lineage.parent.id}`}>{t.lineage.parent.name}</Link>{t.lineage.parent_version ? ` v${t.lineage.parent_version.number}` : ""}</span>}
            {t.archived_at && <span className="tag bad">archived</span>}
          </div>
        </div>
        <div className="row">
          <button className="btn accent" disabled={!v} onClick={() => { c.ensureTemplate(t); setUseOpen(true); }}>Use template</button>
          {t.role === "copy" ? <Link className="btn" to={`/templates/${t.id}/edit`}>Edit copy</Link> : <button className="btn secondary" disabled={!v} onClick={() => copy()}>Copy and edit</button>}
          {!v && t.role === "original" && <Link className="btn secondary" to={`/templates/new?id=${t.id}`}>Continue scan</Link>}
          {v && <a className="btn secondary" href={v.download_url}>Export bundle</a>}
          {t.archived_at ? <button className="btn ghost" onClick={() => act("unarchive", {}, "Restored to the library")}>Restore</button>
            : <button className="btn ghost" onClick={() => act("archive", {}, "Archived — versions and assets used by outputs are kept")}>Archive</button>}
        </div>
      </div>
      {(t.busy || busyJob) && <div className="card flat" style={{ marginBottom: 16 }}><JobLine job={busyJob} label={t.busy?.kind || busyJob?.kind} /><Events job={busyJob} /></div>}
      {t.draft?.copy_check?.reproduces_approved_baseline && (
        <div className={`notice ${t.draft.copy_check.reproduces_approved_baseline.status === "pass" ? "ok" : "bad"}`} style={{ marginBottom: 16 }}>
          {t.draft.copy_check.reproduces_approved_baseline.status === "pass" ? "Inherited baseline reproduced exactly here (0 px differ); this copy inherits the original's checks."
            : `The inherited baseline did not reproduce here (${t.draft.copy_check.reproduces_approved_baseline.unequal_pixels ?? "?"} px differ); editable adaptation is disabled for this copy until that is resolved.`}
        </div>
      )}
      {useOpen && <Composer c={c} templates={[t]} open={useOpen} onOpen={setUseOpen} title={`Use ${t.name} with your products`} />}
      <div className="split">
        <div className="stack">
          {m ? <CompareViewer arts={arts} fileUrl={fileUrl} /> : <div className="viewer"><img src={t.thumb_url} alt={t.name} /></div>}
          {v && (
            <div className="card flat">
              <span className="label">Use in generation</span>
              <p className="small" style={{ margin: "6px 0" }}><strong>Editable adaptation:</strong> {v.eligibility.adapt.eligible ? "available" : "unavailable"}
                {v.eligibility.adapt.reasons.length > 0 && ` — ${v.eligibility.adapt.reasons.join("; ")}`}</p>
              {v.eligibility.adapt.limitations.length > 0 && <ul className="tight small muted">{v.eligibility.adapt.limitations.map((x) => <li key={x}>{x}</li>)}</ul>}
              <p className="small" style={{ margin: "6px 0" }}><strong>Creative generation:</strong> available with a configured image provider; makes new images without preservation claims.</p>
              <p className="small muted">Slots: {v.slots.map((s) => `${s.role}${s.required ? "*" : ""}`).join(", ") || "none"}</p>
            </div>
          )}
          <div className="card flat">
            <span className="label">Organise</span>
            <div className="row" style={{ marginTop: 6 }}>
              <select aria-label="Collection" value={t.collection_id || ""} onChange={async (e) => { await api.patch(`/api/templates/${t.id}`, { collection_id: e.target.value }); load(); }}>
                <option value="">No collection</option>{cols.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
              <input type="text" aria-label="Tags" placeholder="tags, comma separated" defaultValue={t.tags.join(", ")}
                     onBlur={async (e) => { await api.patch(`/api/templates/${t.id}`, { tags: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) }); load(); }} />
            </div>
            {t.children && t.children.length > 0 && <p className="small" style={{ marginTop: 8 }}>Copies: {t.children.map((x) => <Link key={x.id} to={`/templates/${x.id}`} style={{ marginRight: 8 }}>{x.name}</Link>)}</p>}
          </div>
          {v && (
            <details className="card flat">
              <summary><strong>Renderer and baseline</strong> <span className="muted small">advanced</span></summary>
              <dl className="kv small" style={{ marginTop: 10 }}>
                <dt>Pinned renderer</dt><dd>{v.baseline?.pin?.channel} {v.baseline?.pin?.browser_version}</dd>
                <dt>Pinned at</dt><dd>{v.baseline?.pin?.pinned_at || "—"}</dd>
                <dt>Text policy</dt><dd>{v.baseline?.pin?.text_rendering || <span className="tag warn">not recorded (legacy pin)</span>}</dd>
              </dl>
              <p className="small muted">If the browser changed, renders stop with “renderer drift”. Preview a migration, review the actual pixel differences, then confirm that exact preview.</p>
              <button className="btn secondary small" onClick={async () => { try { const r = await api.post<any>(`/api/templates/${t.id}/migrations`, { version_id: v.id }); setMig({ id: r.migration_id, job: r.job.id }); setMigData(null); } catch (e) { toast(errText(e), true); } }}>Preview renderer migration</button>
              {migJob && <div style={{ marginTop: 10 }}><JobLine job={migJob} label="Migration preview" /></div>}
              {migData?.data?.preview_id && migData.status === "previewed" && (
                <div className="notice" style={{ marginTop: 10 }}>
                  <p className="small">{migData.data.status === "no_hard_drift" ? "No hard renderer difference." : "The renderer differs from the pin."} {migData.data.vs_approved_baseline?.unequal_pixels} px differ from the approved baseline. Preview <code>{migData.data.preview_id}</code>.</p>
                  {migData.data.candidate && <p className="small">Candidate saved with the preview record; confirming adopts that exact file.</p>}
                  <button className="btn small" onClick={async () => { try { const r = await api.post<any>(`/api/templates/${t.id}/migrations/${migData.id}/confirm`, { preview_id: migData.data.preview_id }); setJobId(r.id); setMigData(null); } catch (e) { toast(errText(e), true); } }}>Confirm this preview</button>
                </div>
              )}
              <Dev data={{ engine_id: t.engine_id, version: v }} />
            </details>
          )}
        </div>
        <div className="stack">
          {m ? <Inspector t={t} m={m} fileUrl={fileUrl} versions={t.versions} onCopy={(ver) => copy(ver)} canRestore
                          onRestore={(ver) => act("restore", { version_id: ver.id }, `Restoring version ${ver.number} as a new version`)} />
            : <div className="notice">This template has not been measured yet. <Link to={`/templates/new?id=${t.id}`}>Continue the scan</Link>.</div>}
        </div>
      </div>
    </>
  );
}
