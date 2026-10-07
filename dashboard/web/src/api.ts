// Typed client for the dashboard API. Errors carry the server's code, plain message and details.

export class ApiError extends Error {
  code: string;
  status: number;
  detail: Record<string, unknown>;
  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function request<T>(method: string, url: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { "X-DNA-Request": "1" };
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  const ctype = res.headers.get("content-type") || "";
  if (!res.ok) {
    let code = "http_error", message = `Request failed (${res.status})`, detail = {};
    if (ctype.includes("json")) {
      const j = await res.json().catch(() => ({}));
      if (j?.error) ({ code, message, detail } = { code: j.error.code, message: j.error.message, detail: j.error.detail || {} });
    }
    if (res.status === 401 && code === "unauthorized") window.dispatchEvent(new CustomEvent("dna:unauthorized"));
    throw new ApiError(res.status, code, message, detail);
  }
  if (ctype.includes("json")) return (await res.json()) as T;
  return (await res.blob()) as unknown as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  form: <T>(url: string, form: FormData) => request<T>("POST", url, undefined, form),
};

export async function download(url: string, body: unknown, fallbackName: string) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-DNA-Request": "1" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new ApiError(res.status, j?.error?.code || "http_error", j?.error?.message || "Download failed", j?.error?.detail || {});
  }
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || fallbackName;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ------------------------------------------------------------------ types (subset of the API's JSON)
export type Labeled = { value: unknown; status: string; source?: string; mock?: boolean };
export type Asset = {
  id: string; sha256: string; role: string; original_name: string; mime: string; bytes: number; width: number; height: number;
  source_kind: string; source_url?: string; page_url?: string; metadata: Record<string, any>; provenance: Record<string, any>;
  preview_url: string; thumb_url: string; original_url: string;
};
export type Slot = {
  id: string; role: string; type: string; node: string; limits: Record<string, any>; required: boolean; locked: string[];
  fit: string; min_size?: number; template_text?: string | null; geometry?: Record<string, number>;
};
export type Eligibility = { eligible: boolean; reasons: string[]; limitations: string[] };
export type Version = {
  id: string; template_id: string; number: number; readiness: string; readiness_label: string; created_from: string;
  parent_version_id?: string; acceptance?: Record<string, any>; created_at: string; bundle_sha256: string; scene_sha256: string;
  design_variant?: string; design_head?: number; canvas: { width: number; height: number }; slots: Slot[];
  eligibility: { adapt: Eligibility; creative: Eligibility }; baseline: any; editability: any; unresolved: string[];
  thumb_url: string; download_url: string;
};
export type Job = {
  id: string; kind: string; status: string; stage?: string; attempts: number; result?: any; error?: any; template_id?: string;
  created_at: string; started_at?: string; finished_at?: string; cancel_requested?: number; events?: JobEvent[];
};
export type JobEvent = { id: number; at: string; stage?: string; level: string; message: string; data?: any };
export type Template = {
  id: string; name: string; role: "original" | "copy"; engine_id: string; parent_template_id?: string; parent_version_id?: string;
  collection_id?: string; tags: string[]; passport: Record<string, Labeled>; readiness: string; readiness_label: string;
  status: "draft" | "library" | "archived"; archived_at?: string; aspect_ratio?: string; width?: number; height?: number; medium?: string;
  created_at: string; updated_at: string; current_version: Version | null; thumb_url: string; source_asset_id?: string;
  busy: { id: string; kind: string; stage?: string } | null;
  draft?: Record<string, any>; draft_revision?: number; design_variant?: string; versions?: Version[];
  lineage?: { parent: { id: string; name: string }; parent_version?: { id: string; number: number } };
  children?: { id: string; name: string }[]; jobs?: Job[];
};
export type Product = {
  id: string; name: string; primary_asset_id?: string; detail_asset_ids: string[]; description: string; facts: string[];
  instructions: string; primary_asset?: Asset | null; detail_assets: Asset[]; created_at: string; updated_at: string;
};
export type ResolvedSlot = {
  slot_id: string; role: string; node: string; value: string | null; source: string | null; approved: boolean; required: boolean;
  locked: string[]; limits: Record<string, any>; template_text?: string | null; ai_draft?: { value: string; note: string; mock?: boolean } | null;
  hidden: boolean; problems: string[];
};
export type Pair = {
  pair_id: string; status: "ready" | "warning" | "error"; problems: string[]; warnings: string[]; included: boolean; variant_index: number;
  product_id: string; template_id: string; template_version_id: string; mode: string; language: string; slots: ResolvedSlot[];
  image: { slot_id: string; node: string; role: string; asset_id?: string } | null; instructions: string[];
  template: { id: string; name: string; version_id: string; number: number; readiness: string; canvas: { width: number; height: number } };
  product: { id: string; name: string; description: string; facts: string[]; primary_asset_id?: string };
  fit: any; preview: any; version_check?: any; pair_mode?: string | null; pair_language?: string | null; pair_instructions?: string | null;
  inputs_hash: string;
};
export type Batch = {
  id: string; name: string; status: string; revision: number; template_versions: { template_id: string; version_id: string }[];
  product_ids: string[]; defaults: Record<string, any>; product_overrides: Record<string, any>; run_id?: string;
};
export type Matrix = {
  batch: Batch; pairs: Pair[]; providers: Record<string, { provider: string; mock: boolean } | null>;
  counts: { proposed: number; included: number; excluded: number; blocked: number }; detached: string[];
};
export type OutputFile = { kind: string; name: string; sha256: string; bytes: number; width?: number; height?: number; url: string };
export type Output = {
  id: string; run_id: string; pair_id: string; revision: number; parent_output_id?: string; product_id: string; template_id: string;
  template_version_id: string; mode: string; language: string; status: string; review_state: string; checks: any; limitations: string[];
  error: any; inputs: any; provenance: any; files: OutputFile[]; created_at: string; updated_at: string; job_id?: string;
  revisions?: { id: string; revision: number; status: string }[]; events?: JobEvent[]; provider_requests?: any[];
};
export type Run = {
  id: string; batch_id: string; name: string; created_at: string; status: string; counts: Record<string, number>; outputs: number;
};

export const READINESS: Record<string, string> = {
  scan_in_progress: "Draft / scan in progress", scanned: "Scanned", partial_baseline: "Partial rebuild",
  editable_close: "Editable match", exact_pixels: "Exact pixel match",
};
export const MODES: Record<string, string> = {
  adapt: "Editable template adaptation", creative: "Creative reference generation", creative_slot: "Generated photo in the template",
};
