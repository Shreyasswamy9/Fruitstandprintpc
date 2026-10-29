export class ApiError extends Error {
  status: number;
  code: string;
  details: any;
  constructor(status: number, code: string, message: string, details?: any) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Listener = (err: ApiError) => void;
const authListeners = new Set<Listener>();
export function onAuthError(fn: Listener) {
  authListeners.add(fn);
  return () => {
    authListeners.delete(fn);
  };
}

function toError(status: number, body: any): ApiError {
  const payload = body?.detail && typeof body.detail === "object" ? body.detail : body;
  const message =
    payload?.message ??
    (typeof body?.detail === "string" ? body.detail : null) ??
    (status === 422 && Array.isArray(body?.detail) ? "Some values were not accepted." : `Request failed (${status}).`);
  return new ApiError(status, payload?.error ?? "error", message, payload?.details);
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "X-PrintHub": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the print hub. Check your network connection.");
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = toError(res.status, data);
    if (res.status === 401 || err.code === "password_change_required") authListeners.forEach((fn) => fn(err));
    throw err;
  }
  return data as T;
}

export const get = <T = any>(path: string) => api<T>("GET", path);
export const post = <T = any>(path: string, body: unknown = {}) => api<T>("POST", path, body);
export const patch = <T = any>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const del = <T = any>(path: string) => api<T>("DELETE", path);

/** Upload one file as the raw request body, reporting progress (0..1). */
export function uploadFile(file: File, onProgress: (fraction: number) => void, signal?: AbortSignal): Promise<HubFile> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/files");
    xhr.setRequestHeader("X-PrintHub", "1");
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(toError(xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "The upload was interrupted. Check the connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled."));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}

/** Random key for duplicate-submission protection. Works on plain-HTTP LAN origins too. */
export function newKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface User {
  id: number;
  username: string;
  display_name: string;
  role: "employee" | "admin";
  must_change_password: boolean;
  station: boolean;
}

export interface PublicSettings {
  station_name: string;
  station_subtitle: string;
  appearance_theme: "system" | "light" | "dark";
  appearance_motion: "full" | "reduced";
  appearance_density: "comfortable" | "compact";
  station_idle_logout_minutes: number;
  file_retention_hours: number;
}

export interface Bootstrap {
  version: string;
  mode: "production" | "demo";
  station: boolean;
  settings: PublicSettings;
  needs_admin_setup: boolean;
  limits: { max_file_mb: number; max_files_per_job: number; max_pdf_pages: number; types: string[] };
}

export interface HubFile {
  id: string;
  name: string;
  kind: "pdf" | "image";
  mime: string;
  size_bytes: number;
  pages: number | null;
  width_pt: number | null;
  height_pt: number | null;
  notes: string[];
  expires_at: number;
  available: boolean;
}

export interface Reason {
  keyword: string;
  severity: "error" | "warning" | "report";
  explanation: string;
  known: boolean;
}

export interface Marker {
  name: string;
  type: string | null;
  color: string | null;
  level: number | null;
  low: number | null;
  note?: string;
}

export type PrinterState = "ready" | "busy" | "attention" | "stopped" | "offline" | "unknown" | "disabled";

export interface Printer {
  id: string;
  display_name: string;
  location: string;
  make_model: string;
  image: string;
  enabled: boolean;
  simulated: boolean;
  status: {
    state: PrinterState;
    label: string;
    message: string;
    reasons: Reason[];
    markers: Marker[] | null;
    reachability: { checked: boolean; reachable: boolean | null; detail: string } | null;
    checked_at: number | null;
    error: string | null;
  };
  capability_summary: { color: boolean; duplex: boolean; media: string[]; finishing: string[]; max_copies: number | null } | null;
  capabilities_error: string | null;
  defaults: Settings;
  queue_name?: string;
  connection?: string;
  device_uri?: string;
  notes?: string;
  sort_order?: number;
}

export interface Choice {
  key: string;
  label: string;
}
export interface Media extends Choice {
  width_mm: number;
  height_mm: number;
}

export interface Capabilities {
  source: "ipp" | "simulated";
  copies: { min: number; max: number } | null;
  color_modes: Choice[];
  sides: Choice[];
  media: Media[];
  orientations: Choice[];
  page_ranges: boolean;
  scaling: Choice[];
  media_sources: Choice[];
  media_types: Choice[];
  qualities: Choice[];
  collate: boolean;
  finishings: Choice[];
  formats: { pdf: boolean; jpeg: boolean; png: boolean };
  defaults: Partial<Record<string, string>>;
}

export interface Settings {
  copies?: number;
  color_mode?: string;
  sides?: string;
  media?: string;
  orientation?: string;
  scaling?: string;
  media_source?: string;
  media_type?: string;
  quality?: string;
  collate?: boolean;
  finishings?: string[];
}

export interface Preset {
  id: number;
  name: string;
  description: string;
  settings: Settings;
  builtin: boolean;
  compatibility?: { applicable: Settings; unsupported: Record<string, string> };
}

export type ItemStatus =
  | "ready"
  | "submitting"
  | "queued"
  | "held"
  | "processing"
  | "stopped"
  | "completed"
  | "cancelled"
  | "failed"
  | "unknown";
export type JobStatus = "submitting" | "in_progress" | "completed" | "partial" | "failed" | "cancelled" | "unknown";

export interface JobItem {
  id: number;
  position: number;
  name: string;
  kind: string;
  pages: number | null;
  page_ranges: string | null;
  status: ItemStatus;
  message: string;
  reasons: Reason[];
  backend_job_id: string | null;
  reached_print_system: boolean;
  attempts: number;
  submitted_at: number | null;
  finished_at: number | null;
  file_available: boolean;
}

export interface Job {
  id: string;
  reference: string;
  correlation_id: string;
  status: JobStatus;
  simulated: boolean;
  printer: { id: string; display_name: string; location: string; enabled: number } | null;
  owner: { id: number; display_name: string } | null;
  own: boolean;
  settings: Settings;
  settings_labels: Record<string, string>;
  /** [label, value] pairs captured from the printer's capabilities when the job was submitted */
  settings_display: [string, string][];
  preset_name: string | null;
  reprint_of: string | null;
  created_at: number;
  updated_at: number;
  finished_at: number | null;
  items: JobItem[];
  counts: Record<string, number>;
  attention: boolean;
  can_cancel: boolean;
  can_retry: boolean;
  can_reprint: boolean;
  files_retained: boolean;
  cancel_results?: { position: number; result: string; message: string }[];
}

export interface TimelineEvent {
  ts: number;
  level: "debug" | "info" | "warning" | "error";
  category: string;
  event: string;
  message: string;
  item_id: number | null;
  details?: Record<string, unknown>;
}

export interface DiagEvent extends TimelineEvent {
  id: number;
  details: Record<string, unknown>;
  correlation_id: string | null;
  job_id: string | null;
  printer_id: string | null;
  user: string | null;
  help: string | null;
}
