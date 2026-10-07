// Original / Rebuilt baseline / Comparison views — each offered only when its actual artifact exists.
import { useState } from "react";

export type Arts = { reference?: string | null; baseline?: string | null; side_by_side?: string | null; overlay_50?: string | null;
  diff_heatmap?: string | null; crops?: Record<string, string>; annotated?: string | null };

export default function CompareViewer({ arts, fileUrl }: { arts: Arts; fileUrl: (rel: string) => string }) {
  const modes = [
    ["original", "Original", arts.reference], ["baseline", "Rebuilt baseline", arts.baseline],
    ["compare", "Comparison", arts.baseline && arts.reference ? "yes" : null], ["annotated", "Annotated scan", arts.annotated],
  ].filter((m) => m[2]) as [string, string, string][];
  const [mode, setMode] = useState(modes[0]?.[0] || "original");
  const [cmp, setCmp] = useState<"side" | "overlay" | "heat" | "crops">("side");
  const [mix, setMix] = useState(50);
  const missing = !arts.baseline;
  return (
    <div className="stack">
      <div className="row between">
        <div className="seg" role="group" aria-label="Preview">
          {modes.map(([k, label]) => <button key={k} aria-pressed={mode === k} onClick={() => setMode(k)}>{label}</button>)}
        </div>
        {mode === "compare" && (
          <div className="seg" role="group" aria-label="Comparison view">
            {([["side", "Side by side"], ["overlay", "Overlay"], ["heat", "Heatmap"], ["crops", "Regions"]] as const).map(([k, l]) => (
              <button key={k} aria-pressed={cmp === k} onClick={() => setCmp(k)} disabled={(k === "heat" && !arts.diff_heatmap) || (k === "crops" && !Object.keys(arts.crops || {}).length)}>{l}</button>
            ))}
          </div>
        )}
      </div>
      {mode === "original" && arts.reference && <div className="viewer"><img className="checker" src={fileUrl(arts.reference)} alt="Original reference (canonical sRGB copy)" /></div>}
      {mode === "annotated" && arts.annotated && <div className="viewer"><img src={fileUrl(arts.annotated)} alt="Annotated scan with element bounds" /></div>}
      {mode === "baseline" && arts.baseline && <div className="viewer"><img className="checker" src={fileUrl(arts.baseline)} alt="Rebuilt baseline rendered by the pinned engine" /></div>}
      {mode === "compare" && cmp === "side" && arts.side_by_side && <div className="viewer"><img src={fileUrl(arts.side_by_side)} alt="Reference (left) and rebuild (right)" /></div>}
      {mode === "compare" && cmp === "overlay" && arts.reference && arts.baseline && (
        <div className="stack">
          <div className="viewer overlay-stack">
            <img src={fileUrl(arts.reference)} alt="Reference" />
            <img src={fileUrl(arts.baseline)} alt="Rebuild overlaid" style={{ opacity: mix / 100 }} />
          </div>
          <label className="row small"><span className="label">Reference</span>
            <input type="range" min={0} max={100} value={mix} onChange={(e) => setMix(+e.target.value)} aria-label="Overlay mix" style={{ flex: 1 }} />
            <span className="label">Rebuild</span></label>
        </div>
      )}
      {mode === "compare" && cmp === "heat" && arts.diff_heatmap && (
        <div className="stack"><div className="viewer"><img src={fileUrl(arts.diff_heatmap)} alt="Difference heatmap" /></div>
          <p className="small muted">Max channel difference × 4: black = identical, red → yellow = larger differences.</p></div>
      )}
      {mode === "compare" && cmp === "crops" && (
        <div className="stack">
          {Object.entries(arts.crops || {}).map(([k, rel]) => (
            <figure key={k} style={{ margin: 0 }}><figcaption className="label">{k} — reference | rebuild | difference</figcaption>
              <img src={fileUrl(rel)} alt={`Region ${k}: reference, rebuild and difference`} style={{ maxWidth: "100%", border: "1px solid var(--rule)", borderRadius: 6 }} /></figure>
          ))}
        </div>
      )}
      {missing && <p className="small muted">No rebuilt baseline yet: rebuild and compare to see the actual render and its comparison.</p>}
    </div>
  );
}
