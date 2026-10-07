// Element boxes over the reference: select, drag to move, drag the corner to resize, or draw a new box.
// Coordinates are canvas pixels. Arrow keys nudge the selected box by 1 px (Shift: 10 px).
import { useRef, useState, type PointerEvent as RPE } from "react";

export type El = {
  key: string; type: "text" | "image" | "shape" | "logo" | "background"; role: string; bbox: number[]; text?: string;
  align?: "left" | "center" | "right"; slot?: boolean; status?: "proposed" | "accepted" | "rejected"; source?: string;
  confidence?: string; note?: string; edited?: boolean;
};

export default function ElementCanvas({ src, width, height, elements, selected, onSelect, onChange, drawing, onDrawn, readOnly = false }: {
  src: string; width: number; height: number; elements: El[]; selected: string | null; onSelect: (k: string | null) => void;
  onChange?: (k: string, bbox: number[]) => void; drawing?: boolean; onDrawn?: (bbox: number[]) => void; readOnly?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<number[] | null>(null);
  const drag = useRef<{ mode: "move" | "resize" | "draw"; key?: string; x0: number; y0: number; box: number[] } | null>(null);
  const scale = () => (ref.current ? ref.current.clientWidth / width : 1);
  const pt = (e: RPE) => {
    const r = ref.current!.getBoundingClientRect();
    const k = scale();
    return [Math.max(0, Math.min(width, (e.clientX - r.left) / k)), Math.max(0, Math.min(height, (e.clientY - r.top) / k))];
  };
  const down = (e: RPE, key?: string, mode: "move" | "resize" = "move") => {
    if (readOnly) { if (key) onSelect(key); return; }
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const [x, y] = pt(e);
    if (drawing && !key) { drag.current = { mode: "draw", x0: x, y0: y, box: [x, y, 0, 0] }; setDraft([x, y, 0, 0]); return; }
    if (!key) { onSelect(null); return; }
    onSelect(key);
    const el = elements.find((x) => x.key === key)!;
    drag.current = { mode, key, x0: x, y0: y, box: [...el.bbox] };
  };
  const move = (e: RPE) => {
    const d = drag.current;
    if (!d) return;
    const [x, y] = pt(e);
    const dx = x - d.x0, dy = y - d.y0;
    if (d.mode === "draw") { setDraft([Math.min(d.x0, x), Math.min(d.y0, y), Math.abs(dx), Math.abs(dy)]); return; }
    const b = d.box;
    const nb = d.mode === "move"
      ? [Math.round(Math.max(0, Math.min(width - b[2], b[0] + dx))), Math.round(Math.max(0, Math.min(height - b[3], b[1] + dy))), b[2], b[3]]
      : [b[0], b[1], Math.round(Math.max(4, Math.min(width - b[0], b[2] + dx))), Math.round(Math.max(4, Math.min(height - b[1], b[3] + dy)))];
    onChange?.(d.key!, nb);
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.mode === "draw" && draft) {
      const b = draft.map((v) => Math.round(v));
      setDraft(null);
      if (b[2] >= 6 && b[3] >= 6) onDrawn?.(b);
    }
  };
  const key = (e: React.KeyboardEvent) => {
    if (!selected || readOnly) return;
    const el = elements.find((x) => x.key === selected);
    if (!el) return;
    const step = e.shiftKey ? 10 : 1;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (!d) return;
    e.preventDefault();
    const b = el.bbox;
    onChange?.(selected, [Math.max(0, b[0] + d[0]), Math.max(0, b[1] + d[1]), b[2], b[3]]);
  };
  const pct = (v: number, of: number) => `${(100 * v) / of}%`;
  return (
    <div ref={ref} className="stage viewer" tabIndex={0} onKeyDown={key} onPointerDown={(e) => down(e)} onPointerMove={move} onPointerUp={up}
         aria-label="Reference with element boxes. Select a box, then use arrow keys to nudge it." style={{ cursor: drawing ? "crosshair" : "default" }}>
      <img src={src} alt="Reference design" draggable={false} />
      {elements.filter((x) => x.type !== "background").map((el) => (
        <div key={el.key} className={`box ${el.type} ${selected === el.key ? "sel" : ""} ${el.status === "rejected" ? "rejected" : ""}`}
             style={{ left: pct(el.bbox[0], width), top: pct(el.bbox[1], height), width: pct(el.bbox[2], width), height: pct(el.bbox[3], height) }}
             onPointerDown={(e) => down(e, el.key)} role="button" aria-label={`${el.type} ${el.role}`} aria-pressed={selected === el.key}>
          <span className="box-tag">{el.role || el.type}{el.status === "proposed" ? " ?" : ""}</span>
          {!readOnly && selected === el.key && <span className="handle" onPointerDown={(e) => down(e, el.key, "resize")} aria-hidden="true" />}
        </div>
      ))}
      {draft && <div className="drawing" style={{ left: pct(draft[0], width), top: pct(draft[1], height), width: pct(draft[2], width), height: pct(draft[3], height) }} />}
    </div>
  );
}
