// "Create a batch" composer, shared by the library and template detail. Selected template VERSIONS are explicit: a newer
// version of a template never replaces a selected one silently. Selection survives navigation and reload.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Batch, type Matrix, type Template } from "../api";
import { errText, useLocal, useToast } from "../lib";
import { ProductTray, useProducts } from "./Products";

export type Picked = { template_id: string; version_id: string; name: string; number: number; thumb_url: string };

export function useComposer() {
  const [picked, setPicked] = useLocal<Picked[]>("dna.composer.templates", []);
  const [products, setProducts] = useLocal<string[]>("dna.composer.products", []);
  const [batchId, setBatchId] = useLocal<string | null>("dna.composer.batch", null);
  const toggleTemplate = (t: Template) => {
    const v = t.current_version;
    if (!v) return;
    setPicked((p) => p.some((x) => x.template_id === t.id) ? p.filter((x) => x.template_id !== t.id)
      : [...p, { template_id: t.id, version_id: v.id, name: t.name, number: v.number, thumb_url: v.thumb_url }]);
  };
  const ensureTemplate = (t: Template) => {
    const v = t.current_version;
    if (v && !picked.some((x) => x.template_id === t.id)) setPicked((p) => [...p, { template_id: t.id, version_id: v.id, name: t.name, number: v.number, thumb_url: v.thumb_url }]);
  };
  const toggleProduct = (id: string) => setProducts((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  return { picked, setPicked, products, setProducts, batchId, setBatchId, toggleTemplate, ensureTemplate, toggleProduct };
}

export default function Composer({ c, templates, open, onOpen, title = "Create a batch" }: {
  c: ReturnType<typeof useComposer>; templates: Template[]; open: boolean; onOpen: (o: boolean) => void; title?: string;
}) {
  const prods = useProducts();
  const nav = useNavigate();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const known = new Map(templates.map((t) => [t.id, t]));
  const count = c.picked.length * c.products.filter((id) => prods.items.some((p) => p.id === id)).length;

  const go = async () => {
    setBusy(true);
    const body = { template_versions: c.picked.map((p) => ({ template_id: p.template_id, version_id: p.version_id })),
                   product_ids: c.products.filter((id) => prods.items.some((p) => p.id === id)) };
    try {
      let id = c.batchId;
      if (id) {
        try {
          const cur = await api.get<Matrix>(`/api/batches/${id}`);
          await api.patch(`/api/batches/${id}`, { base_revision: cur.batch.revision, changes: body });
        } catch { id = null; }
      }
      if (!id) {
        const m = await api.post<Matrix>("/api/batches", { name: `Batch ${new Date().toLocaleDateString()}`, ...body });
        id = (m.batch as Batch).id;
        c.setBatchId(id);
      }
      nav(`/generate?batch=${id}`);
    } catch (e) { toast(errText(e), true); } finally { setBusy(false); }
  };

  return (
    <details className="panel composer" open={open} onToggle={(e) => onOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span><span className="label">Generate</span><br /><strong style={{ fontFamily: "var(--serif)", fontSize: 18 }}>{title}</strong></span>
        <span className="muted small">{c.picked.length} template{c.picked.length === 1 ? "" : "s"} × {c.products.length} product{c.products.length === 1 ? "" : "s"} = {count} output{count === 1 ? "" : "s"}</span>
      </summary>
      <div className="panel-body stack">
        <div className="stack">
          <span className="label">Templates (select cards in the library)</span>
          {c.picked.length === 0 ? <p className="muted small">No templates selected. Tick “Select” on a template card.</p> : (
            <div className="chips">
              {c.picked.map((p) => {
                const t = known.get(p.template_id);
                const newer = t?.current_version && t.current_version.id !== p.version_id ? t.current_version : null;
                return (
                  <span key={p.template_id} className="chip">
                    <img src={p.thumb_url} alt="" />
                    {p.name} <span className="mono">v{p.number}</span>
                    {newer && (
                      <button title={`Use v${newer.number} instead`} onClick={() => c.setPicked((all) => all.map((x) => x.template_id === p.template_id
                        ? { ...x, version_id: newer.id, number: newer.number, thumb_url: newer.thumb_url } : x))}>↑v{newer.number}</button>
                    )}
                    <button aria-label={`Remove ${p.name}`} onClick={() => c.setPicked((all) => all.filter((x) => x.template_id !== p.template_id))}>×</button>
                  </span>
                );
              })}
            </div>
          )}
        </div>
        <ProductTray items={prods.items} selected={c.products} onToggle={c.toggleProduct} onChanged={prods.reload} compact />
        <div className="row between">
          <span className="muted small">Next: review the text and instructions for every output before anything is generated.</span>
          <button className="btn accent" disabled={!c.picked.length || !count || busy} onClick={go}>Continue to content review →</button>
        </div>
      </div>
    </details>
  );
}
