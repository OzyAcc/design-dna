// Template Library: search, filters, collections, the visual card grid and the "Create a batch" composer.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, READINESS, type Template } from "../api";
import Composer, { useComposer } from "../components/Composer";
import { errText, useLocal, useToast } from "../lib";

type ListRes = { templates: Template[]; facets: { aspects: string[]; media: string[]; collections: { id: string; name: string }[] } };

function val(t: Template, k: string) {
  const v = t.passport?.[k]?.value;
  return typeof v === "string" ? v : Array.isArray(v) ? v.join(", ") : "";
}

function Card({ t, selected, onSelect, onCopy, onUse }: { t: Template; selected: boolean; onSelect: () => void; onCopy: () => void; onUse: () => void }) {
  const usable = !!t.current_version;
  const tone = t.readiness === "exact_pixels" || t.readiness === "editable_close" ? "ok" : t.readiness === "partial_baseline" ? "warn" : "";
  return (
    <article className={`tcard ${selected ? "selected" : ""}`} aria-label={t.name}>
      <Link to={`/templates/${t.id}`} className="tcard-art" aria-label={`Open ${t.name}`}>
        <img src={t.thumb_url} alt="" loading="lazy" />
      </Link>
      <span className="tcard-status">
        <span className={`tag ${tone}`}>{t.status === "draft" ? "Draft" : READINESS[t.readiness] || t.readiness}</span>
      </span>
      <div className="tcard-body">
        <div className="row between" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <Link to={`/templates/${t.id}`} className="tcard-name">{t.name}</Link>
          <label className="check small" title={usable ? "Select for a batch" : "Save a version of this template before using it"}>
            <input type="checkbox" checked={selected} onChange={onSelect} disabled={!usable} aria-label={`Select ${t.name} for a batch`} /> Select
          </label>
        </div>
        <div className="tcard-meta">
          {[val(t, "character") || val(t, "theme"), val(t, "goal") || val(t, "usage")].filter(Boolean).join(" · ").slice(0, 140) || "No passport yet"}
        </div>
        <div className="row small muted" style={{ gap: 8 }}>
          {t.aspect_ratio && <span className="mono">{t.aspect_ratio}</span>}
          {t.role === "copy" && <span className="mono">copy</span>}
          {t.current_version && <span className="mono">v{t.current_version.number}</span>}
          {t.busy && <span className="row" style={{ gap: 4 }}><span className="spinner" /> working</span>}
        </div>
        <div className="tcard-actions">
          <Link className="btn secondary small" to={`/templates/${t.id}`}>Open</Link>
          <button className="btn secondary small" onClick={onCopy} disabled={!usable}>Copy</button>
          <button className="btn small" onClick={onUse} disabled={!usable}>Use</button>
        </div>
      </div>
    </article>
  );
}

export default function Library() {
  const [q, setQ] = useLocal("dna.lib.q", "");
  const [f, setF] = useLocal("dna.lib.filters", { collection: "", medium: "", aspect: "", readiness: "", role: "", sort: "recent", archived: 0 });
  const [data, setData] = useState<ListRes | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useLocal("dna.composer.open", false);
  const [newCol, setNewCol] = useState("");
  const c = useComposer();
  const nav = useNavigate();
  const toast = useToast();
  const importRef = useRef<HTMLInputElement>(null);

  const load = () => {
    const p = new URLSearchParams({ q, sort: f.sort, archived: String(f.archived) });
    for (const k of ["collection", "medium", "aspect", "readiness", "role"] as const) if (f[k]) p.set(k, f[k]);
    api.get<ListRes>(`/api/templates?${p}`).then((d) => { setData(d); setErr(""); }).catch((e) => setErr(errText(e)));
  };
  useEffect(() => { const id = setTimeout(load, 200); return () => clearTimeout(id); }, [q, f]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (data?.templates.some((t) => t.busy)) { const id = setTimeout(load, 2500); return () => clearTimeout(id); } }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const copy = async (t: Template) => {
    try { const r = await api.post<{ template: Template }>(`/api/templates/${t.id}/copy`, {}); toast("Copy created — its own identity, the original is unchanged"); nav(`/templates/${r.template.id}`); }
    catch (e) { toast(errText(e), true); }
  };
  const importBundle = async (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    try { const r = await api.form<{ template: Template }>("/api/templates/import", fd); toast("Bundle received; validating and importing"); nav(`/templates/${r.template.id}`); }
    catch (e) { toast(errText(e), true); }
  };
  const addCollection = async () => {
    if (!newCol.trim()) return;
    try { await api.post("/api/collections", { name: newCol }); setNewCol(""); load(); } catch (e) { toast(errText(e), true); }
  };

  const templates = data?.templates || [];
  const filtering = !!(q || f.collection || f.medium || f.aspect || f.readiness || f.role || f.archived);
  return (
    <>
      <div className="page-head">
        <div>
          <span className="label">Library</span>
          <h1>Template Library</h1>
          <p className="lede">Templates rebuilt from designs you like. Open one to understand it, copy it to change it, or select several to generate.</p>
        </div>
        <div className="row">
          <button className="btn secondary" onClick={() => importRef.current?.click()}>Import bundle</button>
          <input ref={importRef} type="file" accept=".dnab,application/zip" hidden onChange={(e) => { const x = e.target.files?.[0]; if (x) importBundle(x); e.target.value = ""; }} />
          <Link className="btn" to="/templates/new">New template</Link>
        </div>
      </div>

      {(templates.length > 0 || c.picked.length > 0) && <Composer c={c} templates={templates} open={open} onOpen={setOpen} />}

      {(templates.length > 0 || filtering) && (
        <div className="filters" role="search">
          <label className="sr-only" htmlFor="lib-q">Search templates</label>
          <input id="lib-q" type="search" placeholder="Search name, theme, goal, message, usage…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select aria-label="Collection" value={f.collection} onChange={(e) => setF({ ...f, collection: e.target.value })}>
            <option value="">All collections</option>
            {data?.facets.collections.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
          <select aria-label="Aspect ratio" value={f.aspect} onChange={(e) => setF({ ...f, aspect: e.target.value })}>
            <option value="">Any aspect</option>
            {data?.facets.aspects.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <select aria-label="Readiness" value={f.readiness} onChange={(e) => setF({ ...f, readiness: e.target.value })}>
            <option value="">Any readiness</option>
            {Object.entries(READINESS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select aria-label="Original or copy" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            <option value="">All templates</option><option value="original">Originals</option><option value="copy">Copies</option>
          </select>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <select aria-label="Sort" value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
              <option value="recent">Recent activity</option><option value="name">Name</option>
            </select>
            <label className="check small" style={{ whiteSpace: "nowrap" }}><input type="checkbox" checked={!!f.archived} onChange={(e) => setF({ ...f, archived: e.target.checked ? 1 : 0 })} /> Archived</label>
          </div>
        </div>
      )}
      {err && <div className="notice bad" role="alert">{err}</div>}

      {data && templates.length === 0 && !filtering && (
        <section className="empty">
          <span className="label">Start here</span>
          <h2>Create your first template from a design you like</h2>
          <p className="muted" style={{ maxWidth: "58ch", margin: "0 auto" }}>
            Add a finished poster, post or ad. It is scanned into an inspectable template — layout, type, colour, image treatment and
            message — that you can reuse for your own products.
          </p>
          <div className="row">
            <Link className="btn" to="/templates/new?via=upload">Upload inspiration</Link>
            <Link className="btn secondary" to="/templates/new?via=paste">Paste image</Link>
            <Link className="btn secondary" to="/templates/new?via=link">Add link</Link>
            <button className="btn secondary" onClick={() => importRef.current?.click()}>Import bundle</button>
          </div>
          <figure style={{ maxWidth: 760, margin: "30px auto 0" }}>
            <img className="help-art" src="/api/help/how-it-works.png" alt="Illustration of the Design DNA flow: scan, model, rebuild, adapt" />
            <figcaption className="illustration-note">Illustration of the concept — not a screenshot of this app and not a measured template.</figcaption>
          </figure>
        </section>
      )}
      {data && templates.length === 0 && filtering && <div className="empty"><h2>No templates match</h2><p className="muted">Clear the search or filters.</p></div>}

      <div className="cards">
        {templates.map((t) => (
          <Card key={t.id} t={t} selected={c.picked.some((p) => p.template_id === t.id)} onSelect={() => c.toggleTemplate(t)}
                onCopy={() => copy(t)} onUse={() => { c.ensureTemplate(t); setOpen(true); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
        ))}
      </div>

      {templates.length > 0 && (
        <div className="row" style={{ marginTop: 30 }}>
          <span className="label">Collections</span>
          <input type="text" placeholder="New collection name" value={newCol} onChange={(e) => setNewCol(e.target.value)} style={{ maxWidth: 260 }} aria-label="New collection name" />
          <button className="btn secondary small" onClick={addCollection}>Add collection</button>
          <span className="muted small">Assign a template to a collection from its detail page.</span>
        </div>
      )}
    </>
  );
}
