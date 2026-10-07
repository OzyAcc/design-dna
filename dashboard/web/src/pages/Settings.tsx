// Settings: provider configuration and real health checks, runtime capabilities, the font library.
import { useRef, useState } from "react";
import { api } from "../api";
import { Dev, errText, useAsync, useToast } from "../lib";
import { Icon, PageHeader } from "../components/ui";

const HEALTH: Record<string, [string, string]> = {
  configured: ["ok", "Configured and reachable"], unconfigured: ["", "Not configured"], unauthorized: ["bad", "Key rejected"],
  rate_limited: ["warn", "Rate limited"], unavailable: ["bad", "Unavailable"], unsupported: ["bad", "Model not available to this key"],
  unknown_outcome: ["warn", "Could not reach the provider"], bad_request: ["bad", "Request rejected"],
};
const KEY_OF: Record<string, string> = { anthropic: "ANTHROPIC_API_KEY", openai: "OPENAI_API_KEY" };

export default function Settings() {
  const prov = useAsync(() => api.get<any[]>("/api/providers"), []);
  const rt = useAsync(() => api.get<any>("/api/runtime"), []);
  const fonts = useAsync(() => api.get<any[]>("/api/fonts"), []);
  const [checking, setChecking] = useState(false);
  const toast = useToast();
  const fontRef = useRef<HTMLInputElement>(null);
  const check = async () => { setChecking(true); try { await api.get(`/api/providers?check=1`); prov.reload(); } finally { setChecking(false); } };
  const caps = rt.data?.engine?.capabilities || {};
  return (
    <>
      <PageHeader eyebrow="Workspace settings" title={<>Make the studio yours<span className="title-dot">.</span></>} description="Connect AI providers, manage fonts and check what your workspace can do." actions={<button className="btn secondary" onClick={check} disabled={checking}><Icon name="settings" size={16} />{checking ? "Checking…" : "Check providers now"}</button>} />
      <div className="grid2">
        <section className="stack">
          <h2>AI providers</h2>
          {prov.error && <div className="notice bad">{prov.error}</div>}
          {(prov.data || []).map((p) => {
            const [tone, label] = HEALTH[p.health?.status] || ["", p.health?.status];
            return (
              <div key={p.name} className="card">
                <div className="row between"><h3 style={{ margin: 0 }}>{p.label}</h3><span className={`tag ${tone}`}>{label}</span></div>
                <p className="small muted">{p.capabilities.map((c: string) => ({ analysis: "design analysis (element proposals)", copy: "copy drafts and edit compilation", image_generation: "image generation" } as any)[c] || c).join(" · ")}</p>
                {p.models && <p className="small">Models: {Object.entries(p.models).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
                {p.health?.detail && <p className="small muted">{p.health.detail}{p.health.checked_at ? ` (checked ${new Date(p.health.checked_at).toLocaleTimeString()})` : ""}</p>}
                {p.mock && <div className="notice bad small">Test-only mock provider. Its results are labelled mock and never count as real analysis or generation.</div>}
                {KEY_OF[p.name] && <KeyForm name={KEY_OF[p.name]} source={p.key_source} onSaved={() => { prov.reload(); toast("Key saved on the server"); }} />}
              </div>
            );
          })}
          <p className="small muted">Keys are stored only on the server (environment, or a 0600 file in the data directory) and are never sent to the browser. A personal ChatGPT or Claude subscription is not an API key.</p>
        </section>
        <section className="stack">
          <h2>Engine</h2>
          {rt.data && (
            <div className="card">
              <dl className="kv small">
                <dt>Renderer</dt><dd>{rt.data.engine?.renderer || rt.data.engine?.error}</dd>
                <dt>Python</dt><dd>{rt.data.python?.python}</dd>
                <dt>Data directory</dt><dd className="mono">{rt.data.data_dir}</dd>
                <dt>Queue</dt><dd>{rt.data.queue.queued} queued · {rt.data.queue.running} running{rt.data.queue.queued > 0 && rt.data.queue.running === 0 ? " — is the worker running? (python -m dna_dashboard worker)" : ""}</dd>
                <dt>Access</dt><dd>{rt.data.auth_required ? "token required" : `open (bound to ${rt.data.bind})`}</dd>
                <dt>Limits</dt><dd>{rt.data.limits.upload_mb} MB uploads · {rt.data.limits.megapixels} MP · links {rt.data.limits.link_mb} MB / {rt.data.limits.link_timeout_s}s</dd>
              </dl>
              <h4 style={{ marginTop: 14 }}>Capabilities reported by the engine</h4>
              <ul className="tight small">{Object.entries(caps).map(([k, v]) => <li key={k}><strong>{k}</strong>: {String(v)}</li>)}</ul>
              <h4>Input adapters</h4>
              <ul className="tight small">{Object.entries(rt.data.adapters).map(([k, v]) => <li key={k}><strong>{k.replace(/_/g, " ")}</strong>: {String(v)}</li>)}</ul>
              <button className="btn secondary small" onClick={async () => { await api.get("/api/runtime?refresh=1"); rt.reload(); }}>Re-run capability report</button>
              <Dev data={rt.data} />
            </div>
          )}
          <h2>Font library</h2>
          <div className="card">
            <p className="small muted">Fonts the scan may rank as candidates and that outputs may use (for example an Arabic-capable font). A matching candidate is never treated as the font’s identity. Check each font’s licence before sharing bundles that embed it.</p>
            <ul className="tight small">{(fonts.data || []).map((f) => <li key={f.sha256}>{f.names.full} <span className="muted">· weight {f.weight} · {f.source}</span></li>)}</ul>
            <button className="btn secondary small" onClick={() => fontRef.current?.click()}>Upload a font (.ttf / .otf)</button>
            <input ref={fontRef} type="file" accept=".ttf,.otf,font/ttf,font/otf" hidden onChange={async (e) => {
              const f = e.target.files?.[0]; e.target.value = ""; if (!f) return;
              const fd = new FormData(); fd.append("file", f);
              try { const r = await api.form<any>("/api/fonts", fd); toast(`Added ${r.names.full}`); fonts.reload(); } catch (x) { toast(errText(x), true); }
            }} />
          </div>
        </section>
      </div>
    </>
  );
}

function KeyForm({ name, source, onSaved }: { name: string; source: string | null; onSaved: () => void }) {
  const [v, setV] = useState("");
  const toast = useToast();
  if (source === "environment") return <p className="small">Key provided by the server environment (<code>{name}</code>).</p>;
  return (
    <form className="row" onSubmit={async (e) => { e.preventDefault(); try { await api.put("/api/providers/credentials", { name, value: v }); setV(""); onSaved(); } catch (x) { toast(errText(x), true); } }}>
      <label className="sr-only" htmlFor={`k-${name}`}>{name}</label>
      <input id={`k-${name}`} type="password" autoComplete="off" placeholder={source ? "a key is saved — paste to replace" : `paste ${name}`} value={v} onChange={(e) => setV(e.target.value)} style={{ flex: 1, minWidth: 180 }} />
      <button className="btn small" type="submit" disabled={!v.trim()}>Save key</button>
      {source === "settings" && <button className="btn ghost small" type="button" onClick={async () => { await api.put("/api/providers/credentials", { name, value: null }); onSaved(); }}>Remove</button>}
    </form>
  );
}
