// Product inputs: name, primary + detail images, description/prompt, supplied facts, extra instructions.
// Facts (what is true about the product) are kept apart from instructions (mood, message, setting you want).
import { useEffect, useState } from "react";
import { api, type Asset, type Product } from "../api";
import { errText, useToast } from "../lib";
import AssetIntake from "./AssetIntake";
import { Dialog, Icon } from "./ui";

export function useProducts() {
  const [items, setItems] = useState<Product[]>([]);
  const [loaded, setLoaded] = useState(false);
  const reload = () => api.get<Product[]>("/api/products").then((p) => { setItems(p); setLoaded(true); }).catch(() => setLoaded(true));
  useEffect(() => { reload(); }, []);
  return { items, loaded, reload };
}

export function ProductEditor({ product, onClose, onSaved }: { product: Product | null; onClose: () => void; onSaved: (p: Product) => void }) {
  const [name, setName] = useState(product?.name || "");
  const [images, setImages] = useState<Asset[]>([...(product?.primary_asset ? [product.primary_asset] : []), ...(product?.detail_assets || [])]);
  const [description, setDescription] = useState(product?.description || "");
  const [facts, setFacts] = useState((product?.facts || []).join("\n"));
  const [instructions, setInstructions] = useState(product?.instructions || "");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const move = (i: number, d: number) => setImages((im) => { const n = [...im]; const j = i + d; if (j < 0 || j >= n.length) return n; [n[i], n[j]] = [n[j], n[i]]; return n; });
  const save = async () => {
    if (saving) return;
    setErr(""); setSaving(true);
    const body = { name: name.trim() || "Untitled product", primary_asset_id: images[0]?.id ?? null, detail_asset_ids: images.slice(1).map((a) => a.id),
                   description, facts: facts.split("\n").map((f) => f.trim()).filter(Boolean), instructions };
    try {
      const p = product ? await api.patch<Product>(`/api/products/${product.id}`, body) : await api.post<Product>("/api/products", body);
      toast(`Saved ${p.name}`); onSaved(p);
    } catch (e) { setErr(errText(e)); } finally { setSaving(false); }
  };
  return (
      <Dialog open onClose={onClose} title={product ? "Edit product" : "Add a product"} className="product-dialog">
        <p className="muted small">Supply photos, facts and instructions to use with your selected templates.</p>
        <label className="field"><span className="label">Name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sage lounge chair" autoFocus /></label>
        <div className="field">
          <span className="label">Images <span className="muted">first = primary</span></span>
          {images.length > 0 && (
            <div className="thumbs" role="list">
              {images.map((a, i) => (
                <div key={a.id} className={`thumb ${i === 0 ? "primary" : ""}`} role="listitem">
                  <img src={a.thumb_url} alt={`${a.original_name}${i === 0 ? " (primary)" : ""}`} />
                  <div className="row" style={{ gap: 2, marginTop: 4 }}>
                    <button className="btn ghost small" aria-label="Move left" onClick={() => move(i, -1)} disabled={i === 0}>←</button>
                    <button className="btn ghost small" aria-label="Move right" onClick={() => move(i, 1)} disabled={i === images.length - 1}>→</button>
                    <button className="btn ghost small" aria-label="Remove image" onClick={() => setImages((im) => im.filter((x) => x.id !== a.id))}>✕</button>
                  </div>
                  {i !== 0 && <button className="btn ghost small" onClick={() => setImages((im) => [a, ...im.filter((x) => x.id !== a.id)])}>Make primary</button>}
                </div>
              ))}
            </div>
          )}
          <AssetIntake role="product" multiple compact onAdded={(as) => setImages((im) => [...im, ...as])} />
        </div>
        <label className="field"><span className="label">Product description / prompt</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="What the product is, in plain words." /></label>
        <label className="field"><span className="label">Supplied facts <span className="muted">one per line</span></span>
          <textarea value={facts} onChange={(e) => setFacts(e.target.value)} rows={3} placeholder={"Solid oak frame\nLinen cushion"} />
          <span className="hint">Only these facts are used. Prices, offers and claims are never invented.</span></label>
        <label className="field"><span className="label">Extra instructions</span>
          <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={2} placeholder="Mood, message or setting you want (not facts)." /></label>
        {err && <div className="notice bad" role="alert">{err}</div>}
        <div className="row"><button className="btn accent" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save product"}<Icon name="check" size={16} /></button><button className="btn ghost" onClick={onClose}>Cancel</button></div>
      </Dialog>
  );
}

export function ProductTray({ items, selected, onToggle, onChanged, compact = false }: {
  items: Product[]; selected: string[]; onToggle: (id: string) => void; onChanged: () => void; compact?: boolean;
}) {
  const [editing, setEditing] = useState<Product | null | "new">(null);
  return (
    <div className="stack">
      <div className="row between">
        <span className="label">Products ({selected.length} selected)</span>
        <button className="btn secondary small" onClick={() => setEditing("new")}><Icon name="plus" size={14} />Add product</button>
      </div>
      {items.length === 0 ? (
        <p className="muted small">No products yet. Add one with a photo, a short description and any instructions.</p>
      ) : (
        <div className="tray">
          {items.map((p) => {
            const on = selected.includes(p.id);
            return (
              <div key={p.id} className={`pcard ${on ? "selected" : ""}`}>
                {p.primary_asset ? <img src={p.primary_asset.thumb_url} alt={p.name} /> : <div style={{ aspectRatio: "1", background: "var(--paper-3)" }} />}
                <div className="pcard-body">
                  <strong>{p.name}</strong>
                  {!compact && <span className="muted">{p.description?.slice(0, 80) || "No description"}</span>}
                  {!p.primary_asset && <span className="tag warn">no primary image</span>}
                  <div className="row" style={{ marginTop: 4 }}>
                    <label className="check"><input type="checkbox" checked={on} onChange={() => onToggle(p.id)} /> Use</label>
                    <button className="btn ghost small" onClick={() => setEditing(p)}>Edit</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {editing && (
        <ProductEditor product={editing === "new" ? null : editing} onClose={() => setEditing(null)}
                       onSaved={(p) => { setEditing(null); onChanged(); if (editing === "new") onToggle(p.id); }} />
      )}
    </div>
  );
}
