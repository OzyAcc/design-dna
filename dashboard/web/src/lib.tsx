// Shared hooks and small components: job polling, toasts, local draft recovery, status display.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Job } from "./api";

const TERMINAL = ["completed", "needs_review", "failed", "cancelled"];

export function useJob(jobId: string | null | undefined, onDone?: (j: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!jobId) { setJob(null); return; }
    let stop = false, timer: number | undefined, after = 0;
    let events: Job["events"] = [];
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${jobId}?after=${after}`);
        events = [...(events || []), ...(j.events || [])];
        if (j.events?.length) after = j.events[j.events.length - 1].id;
        if (stop) return;
        setJob({ ...j, events });
        if (TERMINAL.includes(j.status)) { done.current?.(j); return; }
      } catch { /* transient: keep polling */ }
      timer = window.setTimeout(tick, 900);
    };
    tick();
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [jobId]);
  return job;
}

type Toast = { text: string; bad?: boolean } | null;
const ToastCtx = createContext<(t: Toast) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<Toast>(null);
  useEffect(() => { if (!t) return; const id = setTimeout(() => setT(null), t.bad ? 9000 : 4000); return () => clearTimeout(id); }, [t]);
  return (
    <ToastCtx.Provider value={setT}>
      {children}
      {t && <div className={`toast ${t.bad ? "bad" : ""}`} role="status" aria-live="polite">{t.text}</div>}
    </ToastCtx.Provider>
  );
}
export function useToast() {
  const set = useContext(ToastCtx);
  return useCallback((text: string, bad = false) => set({ text, bad }), [set]);
}
export function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as any;
    const extra = d?.errors?.length ? ` — ${d.errors.slice(0, 3).map((x: any) => x.message || x.msg || x).join("; ")}`
      : d?.blocked?.length ? ` — ${d.blocked.length} output(s) blocked` : "";
    return e.message + extra;
  }
  return e instanceof Error ? e.message : String(e);
}

export function useLocal<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem(key); return s ? (JSON.parse(s) as T) : initial; } catch { return initial; }
  });
  const set = useCallback((x: T | ((p: T) => T)) => {
    setV((prev) => {
      const next = typeof x === "function" ? (x as (p: T) => T)(prev) : x;
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* storage unavailable: state still works */ }
      return next;
    });
  }, [key]);
  return [v, set];
}

export function StatusDot({ status }: { status: string }) {
  const cls = status === "completed" || status === "ready" || status === "pass" ? "ok"
    : status === "running" || status === "queued" ? "run"
    : status === "needs_review" || status === "warning" || status === "pass_with_unknowns" ? "warn"
    : status === "failed" || status === "error" || status === "fail" ? "bad" : "";
  return <span className={`dot ${cls}`} aria-hidden="true" />;
}

export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued", running: "Running", needs_review: "Needs review", completed: "Completed", failed: "Failed", cancelled: "Cancelled",
};

export function JobLine({ job, label }: { job: Job | null; label?: string }) {
  if (!job) return null;
  const last = job.events?.[job.events.length - 1];
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row">
        {!TERMINAL.includes(job.status) ? <span className="spinner" aria-hidden="true" /> : <StatusDot status={job.status} />}
        <strong>{label || job.kind}</strong>
        <span className="muted">{STATUS_LABEL[job.status] || job.status}{last && !TERMINAL.includes(job.status) ? ` — ${last.message}` : ""}</span>
        {!TERMINAL.includes(job.status) && (
          <button className="btn ghost small" onClick={() => api.post(`/api/jobs/${job.id}/cancel`)}>Cancel</button>
        )}
      </div>
      {job.error && (
        <div className={`notice ${job.status === "failed" ? "bad" : "warn"}`}>
          <strong>{job.error.kind === "conflict" ? "Conflict: " : job.error.kind === "provider" ? "Provider: " : job.error.kind === "infrastructure" ? "Infrastructure failure: " : ""}</strong>
          {job.error.message}
          {job.error.detail?.options && <ul className="tight">{job.error.detail.options.map((o: string) => <li key={o}>{o}</li>)}</ul>}
          {job.error.detail?.setup && <div><a href="/settings">Open Settings</a></div>}
        </div>
      )}
    </div>
  );
}

export function Events({ job }: { job: Job | null }) {
  if (!job?.events?.length) return null;
  return (
    <div className="events" aria-label="Job events">
      {job.events.map((e) => (
        <div key={e.id} className={`ev-${e.level}`}>{e.at.slice(11, 19)} {e.stage ? `[${e.stage}] ` : ""}{e.message}</div>
      ))}
    </div>
  );
}

export function Dev({ data, label = "Developer details" }: { data: unknown; label?: string }) {
  return (
    <details className="dev">
      <summary>{label}</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setError(null); } }).catch((e) => { if (live) setError(errText(e)); }).finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1) };
}

export function newKey() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function fmtBytes(n: number) {
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
}
