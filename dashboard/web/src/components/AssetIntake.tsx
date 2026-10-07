// Upload, paste and link intake for both roles. Pasting into a text field still pastes text: clipboard images are only
// taken when the paste is not aimed at a text field. Links are fetched by the server (not by the browser).
import { useEffect, useRef, useState } from "react";
import { api, type Asset } from "../api";
import { errText, fmtBytes } from "../lib";

type Candidate = { url: string; declared_by: string; alt: string; ok: boolean | null; reason?: string; thumb?: string; width?: number; height?: number; bytes?: number };
type PageResult = { kind: "page"; page_url: string; title: string; site_name: string; candidates: Candidate[]; error?: string };

export default function AssetIntake({ role, multiple = false, onAdded, listenPaste = true, compact = false, label }: {
  role: "inspiration" | "product" | "detail"; multiple?: boolean; onAdded: (a: Asset[]) => void; listenPaste?: boolean; compact?: boolean; label?: string;
}) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [url, setUrl] = useState("");
  const [page, setPage] = useState<PageResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const zoneRef = useRef<HTMLDivElement>(null);

  const upload = async (files: File[], kind: "upload" | "paste") => {
    const list = multiple ? files : files.slice(0, 1);
    if (!list.length) return;
    setErr(""); setBusy(kind === "paste" ? "Adding pasted image…" : `Uploading ${list.length} file(s)…`);
    const fd = new FormData();
    list.forEach((f, i) => fd.append("files", f, f.name || `pasted-${i + 1}.png`));
    fd.append("role", role); fd.append("source_kind", kind);
    try {
      const r = await api.form<{ assets: Asset[]; errors: { file: string; message: string }[] }>("/api/assets/upload", fd);
      if (r.errors.length) setErr(r.errors.map((e) => `${e.file}: ${e.message}`).join(" · "));
      if (r.assets.length) onAdded(r.assets);
    } catch (e) { setErr(errText(e)); } finally { setBusy(""); }
  };

  const resolveLink = async (u: string) => {
    if (!u.trim()) return;
    setErr(""); setPage(null); setBusy("Fetching the link on the server…");
    try {
      const r = await api.post<any>("/api/assets/link", { url: u.trim(), role });
      if (r.kind === "image") { onAdded([r.asset]); setUrl(""); }
      else setPage(r);
    } catch (e) { setErr(errText(e)); } finally { setBusy(""); }
  };

  const pick = async (c: Candidate) => {
    if (!page) return;
    setBusy("Importing the chosen image…"); setErr("");
    try {
      const r = await api.post<{ asset: Asset }>("/api/assets/page-image", { url: c.url, role, page_url: page.page_url, title: page.title, site_name: page.site_name, declared_by: c.declared_by, alt: c.alt });
      onAdded([r.asset]); setPage(null); setUrl("");
    } catch (e) { setErr(errText(e)); } finally { setBusy(""); }
  };

  useEffect(() => {
    if (!listenPaste) return;
    const h = (e: ClipboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) && !zoneRef.current?.contains(t)) return;
      const files = Array.from(e.clipboardData?.files || []).filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); upload(files, "paste"); return; }
      const text = e.clipboardData?.getData("text/plain")?.trim();
      if (text && /^https?:\/\/\S+$/i.test(text) && !(t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"))) { e.preventDefault(); setUrl(text); resolveLink(text); }
    };
    window.addEventListener("paste", h);
    return () => window.removeEventListener("paste", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listenPaste, role, multiple]);

  return (
    <div className="stack" ref={zoneRef}>
      <div className={`dropzone ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); upload(Array.from(e.dataTransfer.files), "upload"); }}>
        <p style={{ margin: compact ? 0 : undefined }}>
          <strong>{label || (role === "inspiration" ? "Drop a finished design here" : "Drop product photos here")}</strong>
          {!compact && <><br /><span className="muted small">PNG, JPEG, WebP, TIFF, BMP or GIF (first frame). Or paste an image (⌘/Ctrl+V) anywhere on this page.</span></>}
        </p>
        <div className="row" style={{ justifyContent: "center", marginTop: 10 }}>
          <button className="btn secondary small" type="button" onClick={() => fileRef.current?.click()}>Choose file{multiple ? "s" : ""}</button>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/tiff,image/bmp,image/gif" multiple={multiple} hidden
                 onChange={(e) => { upload(Array.from(e.target.files || []), "upload"); e.target.value = ""; }} />
        </div>
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); resolveLink(url); }}>
        <label className="sr-only" htmlFor={`link-${role}`}>Image or page link</label>
        <input id={`link-${role}`} type="url" placeholder="…or paste a link to an image or a public web page" value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn secondary small" type="submit" disabled={!url.trim() || !!busy}>Add link</button>
      </form>
      {busy && <div className="row muted small"><span className="spinner" /> {busy}</div>}
      {err && <div className="notice bad" role="alert">{err}</div>}
      {page && (
        <div className="panel">
          <div className="panel-head">
            <div><div className="label">Images declared by the page</div><strong>{page.title || page.page_url}</strong>{page.site_name && <span className="muted"> · {page.site_name}</span>}</div>
            <button className="btn ghost small" onClick={() => setPage(null)}>Close</button>
          </div>
          <div className="panel-body stack">
            <p className="small muted">Choose the image you mean. This imports one image the page declares; it does not capture or recover the page’s design. The source page is recorded.</p>
            {page.error && <div className="notice warn">{page.error}</div>}
            <div className="cand-grid">
              {page.candidates.filter((c) => c.ok).map((c) => (
                <button key={c.url} className="cand" onClick={() => pick(c)} title={c.url}>
                  <img src={c.thumb} alt={c.alt || "candidate image"} />
                  <span className="mono">{c.declared_by} · {c.width}×{c.height} · {fmtBytes(c.bytes || 0)}</span>
                </button>
              ))}
            </div>
            {page.candidates.some((c) => c.ok === false) && (
              <details><summary className="small muted">{page.candidates.filter((c) => c.ok === false).length} candidate(s) could not be used</summary>
                <ul className="tight small">{page.candidates.filter((c) => c.ok === false).map((c) => <li key={c.url}><code>{c.url.slice(0, 80)}</code> — {c.reason}</li>)}</ul></details>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
