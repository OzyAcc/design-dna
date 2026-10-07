// Template-first workspace. Counts and previews always come from the real API; no sample content is injected.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, READINESS, type Template } from "../api";
import Composer, { useComposer } from "../components/Composer";
import {
  Dialog,
  EmptyState,
  Icon,
  PageHeader,
  SkeletonCards,
  Spotlight,
} from "../components/ui";
import { errText, useLocal, useToast } from "../lib";

type ListRes = {
  templates: Template[];
  facets: {
    aspects: string[];
    media: string[];
    collections: { id: string; name: string }[];
  };
};
const defaultFilters = {
  collection: "",
  medium: "",
  aspect: "",
  readiness: "",
  role: "",
  sort: "recent",
  archived: 0,
};
function val(t: Template, k: string) {
  const v = t.passport?.[k]?.value;
  return typeof v === "string" ? v : Array.isArray(v) ? v.join(", ") : "";
}

function Card({
  t,
  selected,
  onSelect,
  onCopy,
  onUse,
}: {
  t: Template;
  selected: boolean;
  onSelect: () => void;
  onCopy: () => void;
  onUse: () => void;
}) {
  const usable = !!t.current_version;
  const tone =
    t.readiness === "exact_pixels" || t.readiness === "editable_close"
      ? "ok"
      : t.readiness === "partial_baseline"
        ? "warn"
        : "";
  return (
    <article
      className={`tcard ${selected ? "selected" : ""}`}
      aria-label={t.name}
    >
      <Spotlight className="tcard-content">
        <Link
          to={`/templates/${t.id}`}
          className="tcard-art"
          aria-label={`Open ${t.name}`}
        >
          <img src={t.thumb_url} alt="" loading="lazy" />
          <span className="preview-open">
            <Icon name="arrow" />
          </span>
        </Link>
        <div className="tcard-status">
          <span className={`tag ${tone}`}>
            {t.status === "draft"
              ? "Draft"
              : READINESS[t.readiness] || t.readiness}
          </span>
        </div>
        <div className="tcard-body">
          <div className="row between tcard-title">
            <Link to={`/templates/${t.id}`} className="tcard-name">
              {t.name}
            </Link>
            <label
              className="check card-select"
              title={
                usable
                  ? "Select for a batch"
                  : "Save a version before using this template"
              }
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={onSelect}
                disabled={!usable}
                aria-label={`Select ${t.name} for a batch`}
              />
              <span className="sr-only">Select</span>
            </label>
          </div>
          <div className="tcard-meta">
            {[
              val(t, "character") || val(t, "theme"),
              val(t, "goal") || val(t, "usage"),
            ]
              .filter(Boolean)
              .join(" · ")
              .slice(0, 130) || "Add a purpose to this template"}
          </div>
          <div className="row tcard-specs">
            <span>{t.role === "copy" ? "Editable copy" : "Original"}</span>
            {t.aspect_ratio && <span>{t.aspect_ratio}</span>}
            {t.current_version && <span>v{t.current_version.number}</span>}
            {t.busy && (
              <span className="row">
                <span className="spinner" />
                Working
              </span>
            )}
          </div>
          <div className="tcard-actions">
            <Link className="btn ghost small" to={`/templates/${t.id}`}>
              View template
              <Icon name="arrow" size={14} />
            </Link>
            <button
              className="btn secondary small"
              onClick={onCopy}
              disabled={!usable}
            >
              <Icon name="copy" size={14} />
              Copy
            </button>
            <button className="btn small" onClick={onUse} disabled={!usable}>
              Use
              <Icon name="plus" size={14} />
            </button>
          </div>
        </div>
      </Spotlight>
    </article>
  );
}

export default function Library() {
  const [q, setQ] = useLocal("dna.lib.q", "");
  const [f, setF] = useLocal("dna.lib.filters", defaultFilters);
  const [view, setView] = useLocal("dna.lib.view", "grid");
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [open, setOpen] = useLocal("dna.composer.open", false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [newCol, setNewCol] = useState("");
  const [savingCol, setSavingCol] = useState(false);
  const c = useComposer();
  const nav = useNavigate();
  const toast = useToast();
  const importRef = useRef<HTMLInputElement>(null);
  const sequence = useRef(0);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      sequence.current++;
    };
  }, []);
  const load = () => {
    const request = ++sequence.current;
    setLoading(true);
    const p = new URLSearchParams({
      q,
      sort: f.sort,
      archived: String(f.archived),
    });
    for (const k of [
      "collection",
      "medium",
      "aspect",
      "readiness",
      "role",
    ] as const)
      if (f[k]) p.set(k, f[k]);
    api
      .get<ListRes>(`/api/templates?${p}`)
      .then((d) => {
        if (live.current && request === sequence.current) {
          setData(d);
          setErr("");
        }
      })
      .catch((e) => {
        if (live.current && request === sequence.current) setErr(errText(e));
      })
      .finally(() => {
        if (live.current && request === sequence.current) setLoading(false);
      });
  };
  useEffect(() => {
    sequence.current++;
    const id = setTimeout(load, 200);
    return () => clearTimeout(id);
  }, [q, f]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (data?.templates.some((t) => t.busy)) {
      const id = setTimeout(load, 2500);
      return () => clearTimeout(id);
    }
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const copy = async (t: Template) => {
    try {
      const r = await api.post<{ template: Template }>(
        `/api/templates/${t.id}/copy`,
        {},
      );
      toast("Copy created — the original is preserved");
      nav(`/templates/${r.template.id}`);
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const importBundle = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.form<{ template: Template }>(
        "/api/templates/import",
        fd,
      );
      toast("Bundle received; validating and importing");
      nav(`/templates/${r.template.id}`);
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const addCollection = async () => {
    if (!newCol.trim()) return;
    setSavingCol(true);
    try {
      await api.post("/api/collections", { name: newCol.trim() });
      setNewCol("");
      setCollectionOpen(false);
      load();
      toast("Collection created");
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setSavingCol(false);
    }
  };
  const templates = data?.templates || [];
  const filtering = !!(
    q ||
    f.collection ||
    f.medium ||
    f.aspect ||
    f.readiness ||
    f.role ||
    f.archived
  );
  const advancedCount = [
    f.medium,
    f.aspect,
    f.readiness,
    f.role,
    f.archived,
  ].filter(Boolean).length;
  const clear = () => {
    setQ("");
    setF(defaultFilters);
  };
  const compose = () => {
    setOpen(true);
    requestAnimationFrame(() =>
      document
        .getElementById("batch-composer")
        ?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "instant"
            : "smooth",
          block: "start",
        }),
    );
  };
  return (
    <>
      <PageHeader
        eyebrow="Your creative foundation"
        title={
          <>
            Template Library<span className="title-dot">.</span>
          </>
        }
        description="Collect a design. Understand its DNA. Make it work for you."
        actions={
          <>
            <button
              className="btn secondary"
              onClick={() => importRef.current?.click()}
            >
              <Icon name="upload" size={16} />
              Import bundle
            </button>
            <Link className="btn accent" to="/templates/new">
              <Icon name="plus" size={16} />
              New template
            </Link>
          </>
        }
      />
      <input
        ref={importRef}
        type="file"
        accept=".dnab,application/zip"
        hidden
        onChange={(e) => {
          const x = e.target.files?.[0];
          if (x) importBundle(x);
          e.target.value = "";
        }}
      />
      <Spotlight className="library-intro">
        <div className="intro-copy">
          <span className="intro-symbol">
            <Icon name="layers" size={23} />
          </span>
          <div>
            <strong>Good design starts with a good reference.</strong>
            <p>
              Turn inspiration into an editable system of layout, type, colour
              and rules.
            </p>
          </div>
        </div>
        <Link to="/templates/new?via=upload">
          Add inspiration
          <Icon name="arrow" size={16} />
        </Link>
        <div className="intro-decoration" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </Spotlight>
      <div className="library-toolbar">
        <div className="search-field">
          <Icon name="search" size={18} />
          <input
            id="lib-q"
            type="search"
            aria-label="Search templates"
            placeholder="Search by name, theme, goal or message…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="toolbar-actions">
          <button
            className={`btn secondary ${advancedCount ? "filter-active" : ""}`}
            aria-expanded={filtersOpen}
            aria-controls="library-filters"
            onClick={() => setFiltersOpen(!filtersOpen)}
          >
            <Icon name="filter" size={16} />
            Filters
            {advancedCount > 0 && (
              <span className="count-badge">{advancedCount}</span>
            )}
          </button>
          <select
            aria-label="Sort"
            value={f.sort}
            onChange={(e) => setF({ ...f, sort: e.target.value })}
          >
            <option value="recent">Recently updated</option>
            <option value="name">Name A–Z</option>
          </select>
          <div
            className="seg view-toggle"
            role="group"
            aria-label="Library view"
          >
            <button
              aria-label="Grid view"
              aria-pressed={view === "grid"}
              onClick={() => setView("grid")}
            >
              <Icon name="grid" size={17} />
            </button>
            <button
              aria-label="List view"
              aria-pressed={view === "list"}
              onClick={() => setView("list")}
            >
              <Icon name="list" size={17} />
            </button>
          </div>
        </div>
      </div>
      {filtersOpen && (
        <div className="filters expanded-filters" id="library-filters">
          <label className="field">
            <span className="label">Medium</span>
            <select
              aria-label="Medium"
              value={f.medium}
              onChange={(e) => setF({ ...f, medium: e.target.value })}
            >
              <option value="">Any medium</option>
              {data?.facets.media.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="label">Aspect ratio</span>
            <select
              aria-label="Aspect ratio"
              value={f.aspect}
              onChange={(e) => setF({ ...f, aspect: e.target.value })}
            >
              <option value="">Any aspect</option>
              {data?.facets.aspects.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="label">Readiness</span>
            <select
              aria-label="Readiness"
              value={f.readiness}
              onChange={(e) => setF({ ...f, readiness: e.target.value })}
            >
              <option value="">Any readiness</option>
              {Object.entries(READINESS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="label">Type</span>
            <select
              aria-label="Original or copy"
              value={f.role}
              onChange={(e) => setF({ ...f, role: e.target.value })}
            >
              <option value="">All templates</option>
              <option value="original">Originals</option>
              <option value="copy">Copies</option>
            </select>
          </label>
          <label className="check small">
            <input
              type="checkbox"
              checked={!!f.archived}
              onChange={(e) =>
                setF({ ...f, archived: e.target.checked ? 1 : 0 })
              }
            />
            Include archived
          </label>
        </div>
      )}
      <div className="collection-row">
        <div className="collection-tabs" role="group" aria-label="Collections">
          <button
            className={!f.collection ? "active" : ""}
            aria-pressed={!f.collection}
            onClick={() => setF({ ...f, collection: "" })}
          >
            <Icon name="layers" size={15} />
            All templates
          </button>
          {data?.facets.collections.map((x) => (
            <button
              key={x.id}
              className={f.collection === x.id ? "active" : ""}
              aria-pressed={f.collection === x.id}
              onClick={() => setF({ ...f, collection: x.id })}
            >
              <Icon name="folder" size={15} />
              {x.name}
            </button>
          ))}
        </div>
        <button
          className="btn ghost small"
          onClick={() => setCollectionOpen(true)}
        >
          <Icon name="plus" size={15} />
          Collection
        </button>
      </div>
      {filtering && (
        <div className="active-filter-row">
          <span className="small muted">
            Filtered library{q ? ` · “${q}”` : ""}
          </span>
          <button className="btn ghost small" onClick={clear}>
            <Icon name="close" size={13} />
            Clear filters
          </button>
        </div>
      )}
      {err && (
        <div className="notice bad" role="alert">
          {err}
          <button className="btn ghost small" onClick={load}>
            Try again
          </button>
        </div>
      )}
      {data && templates.length > 0 && (
        <div className="library-count" role="status">
          {loading
            ? "Updating your library…"
            : `${templates.length} template${templates.length === 1 ? "" : "s"} shown`}
          <span className="small muted">
            Select templates to create a batch
          </span>
        </div>
      )}
      {data && templates.length === 0 && !filtering && !err && (
        <EmptyState
          title="Your next design starts here."
          actions={
            <>
              <Link className="btn accent" to="/templates/new?via=upload">
                <Icon name="upload" size={16} />
                Upload inspiration
              </Link>
              <Link className="btn secondary" to="/templates/new?via=paste">
                Paste image
              </Link>
              <Link className="btn secondary" to="/templates/new?via=link">
                <Icon name="link" size={16} />
                Add link
              </Link>
            </>
          }
        >
          <p>
            Add a poster, social post or ad you like. Scan its layout,
            typography, colours and message, then save it as a template for your
            products.
          </p>
          <div className="empty-workflow">
            <span>
              <Icon name="image" />
              Add a reference
            </span>
            <Icon name="chevron" size={14} />
            <span>
              <Icon name="layers" />
              Review its parts
            </span>
            <Icon name="chevron" size={14} />
            <span>
              <Icon name="sparkles" />
              Reuse the template
            </span>
          </div>
        </EmptyState>
      )}
      {data && templates.length === 0 && filtering && !err && (
        <EmptyState
          icon="search"
          title="No templates found."
          actions={
            <button className="btn secondary" onClick={clear}>
              Clear search and filters
            </button>
          }
        >
          <p>Try a different name or broaden your filters.</p>
        </EmptyState>
      )}
      {!data && !err ? (
        <SkeletonCards />
      ) : (
        <div
          className={`cards ${view === "list" ? "list-view" : ""}`}
          aria-busy={loading}
        >
          {templates.map((t) => (
            <Card
              key={t.id}
              t={t}
              selected={c.picked.some((p) => p.template_id === t.id)}
              onSelect={() => c.toggleTemplate(t)}
              onCopy={() => copy(t)}
              onUse={() => {
                c.ensureTemplate(t);
                compose();
              }}
            />
          ))}
        </div>
      )}
      {(templates.length > 0 || c.picked.length > 0) && (
        <div id="batch-composer">
          <Composer c={c} templates={templates} open={open} onOpen={setOpen} />
        </div>
      )}
      {c.picked.length > 0 && (
        <div
          className="selection-dock"
          role="region"
          aria-label="Selected templates"
        >
          <span className="selection-icon">
            <Icon name="check" size={16} />
          </span>
          <span>
            <strong>
              {c.picked.length} template{c.picked.length === 1 ? "" : "s"}{" "}
              selected
            </strong>
            <small>Add products, then review each output.</small>
          </span>
          <button className="btn ghost small" onClick={() => c.setPicked([])}>
            Clear
          </button>
          <button className="btn accent" onClick={compose}>
            Create batch
            <Icon name="arrow" size={16} />
          </button>
        </div>
      )}
      <Dialog
        open={collectionOpen}
        onClose={() => setCollectionOpen(false)}
        title="Create a collection"
      >
        <p className="muted small">
          Group templates by campaign, style or purpose.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addCollection();
          }}
        >
          <label className="field">
            <span className="label">Collection name</span>
            <input
              autoFocus
              type="text"
              aria-label="New collection name"
              placeholder="e.g. Botanical editorials"
              value={newCol}
              onChange={(e) => setNewCol(e.target.value)}
              required
            />
          </label>
          <div className="row">
            <button
              className="btn accent"
              disabled={!newCol.trim() || savingCol}
            >
              {savingCol ? "Creating…" : "Create collection"}
            </button>
            <button
              type="button"
              className="btn ghost"
              onClick={() => setCollectionOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
