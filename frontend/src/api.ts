export type Role = "officer" | "admin" | "auditor" | "forensic" | "judge";
export type Rank = "officer" | "station_head" | "superintendent";

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  rank: Rank;
  station_id: number | null;
  station_name: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  must_change_password: boolean;
}

export interface Party { name: string; role: string }
export interface Assignee { user_id: number; username: string; full_name: string }
export interface Share { user_id: number; username: string; full_name: string; role: string; shared_by: string; created_at: string }
export interface CaseT {
  id: number; case_number: string; fir_number: string | null; title: string; case_type: string | null;
  description: string | null; status: string; station_id: number; created_at: string;
  parties: Party[]; assignees: Assignee[]; shares: Share[]; document_count: number | null;
}

/** Roles/ranks that can open case & document content (view, download, verify) — never "admin" or "auditor". */
export const hasContentAccess = (u: User | null) => !!u && (u.role === "officer" || u.role === "forensic" || u.role === "judge");
/** Only a plain, assigned officer can upload/version/summarise/create cases — senior officers included, reviewers not. */
export const canWrite = (u: User | null) => u?.role === "officer";
export interface VersionT {
  version_no: number; filename: string; content_type: string; size: number; sha256: string;
  uploaded_by: string; uploaded_at: string; change_note: string | null;
  ledger_tx_id: string | null; ledger_block: number | null;
  ai_doc_type: string | null; ai_confidence: number | null; ai_tags: string[];
  ai_entities: Record<string, string[]>; ai_provider: string | null;
  language: string | null; ocr_confidence: number | null; ocr_method: string | null; needs_review: boolean; summary: string | null;
}
export interface DocumentT {
  id: number; uid: string; case_id: number; case_number: string; title: string; doc_type: string;
  description: string | null; created_at: string; current_version: number; versions: VersionT[];
}
export interface VerifyT {
  document_id: number; version_no: number; status: "verified" | "tampered"; reasons: string[];
  stored_sha256: string; recomputed_sha256: string | null; ledger_sha256: string | null;
  ledger_tx_id: string | null; ledger_block: number | null;
}
export interface AuditEntry {
  id: number; ts: string; actor_username: string | null; actor_role: string | null; action: string;
  outcome: string; resource_type: string | null; resource_id: string | null; case_number: string | null;
  ip: string | null; detail: Record<string, unknown>; prev_hash: string; entry_hash: string;
}
export interface Block {
  index: number; ts: string; kind: string; payload: Record<string, unknown>;
  payload_hash: string; prev_hash: string; block_hash: string; tx_id: string;
}
export interface ChainCheck {
  ok: boolean; checked: number; broken_at: number | null; reason: string | null;
  last_anchor?: { audit_id: number; tx_id: string; ts: string } | null;
}
export interface SearchResult {
  cases: { id: number; case_number: string; fir_number: string | null; title: string; case_type: string | null; status: string; parties: string[] }[];
  documents: { document_id: number; title: string; doc_type: string; case_id: number; case_number: string; version_no: number; uploaded_at: string; snippet: string | null; score: number | null }[];
  documents_total: number | null;
  mode: string;
}
export interface CaseSummary { available: boolean; overall: string | null; by_type: Record<string, string>; documents: number }
export interface LedgerStatus { backend: string; channel?: string; chaincode?: string; org?: string; peer?: string; height: number; current_block_hash?: string }
export interface StageToken { stage: "mfa_required" | "mfa_setup_required" | "authenticated"; token: string; must_change_password: boolean }

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

const TOKEN_KEY = "sdms_token";
let token: string | null = null;
try { token = sessionStorage.getItem(TOKEN_KEY); } catch { /* storage unavailable */ }
let onUnauthorized: () => void = () => {};

export function setToken(t: string | null) {
  token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}
export const hasToken = () => token !== null;
/** When the current session token expires (ms since epoch), read from its payload; null if unknown. */
export function tokenExpiresAt(): number | null {
  try {
    const payload = token?.split(".")[1];
    return payload ? JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))).exp * 1000 : null;
  } catch { return null; }
}
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

function messageFrom(status: number, body: any): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc ?? []).slice(1).join(".")}: ${x.msg}`).join("; ");
  if (d && typeof d === "object" && typeof d.message === "string") return d.message;
  return `Request failed (${status})`;
}

async function request<T>(method: string, path: string, opts: { body?: unknown; form?: FormData; token?: string | null; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const tok = opts.token !== undefined ? opts.token : token;
  if (tok) headers.Authorization = `Bearer ${tok}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }

  const res = await fetch(path, { method, headers, body });
  if (opts.raw && res.ok) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("json") ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    // A stage token in login flows is passed explicitly; only a rejected *session* token logs out.
    if (res.status === 401 && opts.token === undefined && token) onUnauthorized();
    throw new ApiError(res.status, messageFrom(res.status, data), (data as any)?.detail);
  }
  return data as T;
}

const qs = (p: Record<string, string | number | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

export const api = {
  login: (username: string, password: string) => request<StageToken>("POST", "/api/auth/login", { body: { username, password }, token: null }),
  mfaVerify: (t: string, code: string) => request<StageToken>("POST", "/api/auth/mfa/verify", { body: { code }, token: t }),
  mfaSetup: (t: string) => request<{ secret: string; otpauth_uri: string }>("POST", "/api/auth/mfa/setup", { token: t }),
  mfaEnable: (t: string, code: string) => request<StageToken>("POST", "/api/auth/mfa/enable", { body: { code }, token: t }),
  me: () => request<User>("GET", "/api/auth/me"),
  logout: () => request<void>("POST", "/api/auth/logout"),
  refresh: () => request<StageToken>("POST", "/api/auth/refresh"),
  changePassword: (current_password: string, new_password: string) =>
    request<StageToken>("POST", "/api/auth/change-password", { body: { current_password, new_password } }),

  cases: () => request<CaseT[]>("GET", "/api/cases"),
  case: (id: number) => request<CaseT>("GET", `/api/cases/${id}`),
  createCase: (b: { title: string; fir_number?: string; case_type?: string; description?: string; parties: Party[]; officer_ids?: number[] }) =>
    request<CaseT>("POST", "/api/cases", { body: b }),
  assign: (caseId: number, userId: number) => request<CaseT>("POST", `/api/cases/${caseId}/assignments`, { body: { user_id: userId } }),
  unassign: (caseId: number, userId: number) => request<CaseT>("DELETE", `/api/cases/${caseId}/assignments/${userId}`),
  share: (caseId: number, userId: number) => request<CaseT>("POST", `/api/cases/${caseId}/shares`, { body: { user_id: userId } }),
  unshare: (caseId: number, userId: number) => request<CaseT>("DELETE", `/api/cases/${caseId}/shares/${userId}`),

  users: () => request<User[]>("GET", "/api/users"),
  reviewers: () => request<User[]>("GET", "/api/users/reviewers"),
  createUser: (b: { username: string; full_name: string; password: string }) => request<User>("POST", "/api/users", { body: b }),
  setActive: (id: number, is_active: boolean, rank: Rank) => request<User>("PATCH", `/api/users/${id}`, { body: { is_active, rank } }),
  resetMfa: (id: number) => request<User>("POST", `/api/users/${id}/reset-mfa`),
  unlock: (id: number) => request<User>("POST", `/api/users/${id}/unlock`),

  documents: (caseId: number) => request<DocumentT[]>("GET", `/api/cases/${caseId}/documents`),
  document: (id: number) => request<DocumentT>("GET", `/api/documents/${id}`),
  upload: (caseId: number, form: FormData) => request<DocumentT>("POST", `/api/cases/${caseId}/documents`, { form }),
  uploadVersion: (id: number, form: FormData) => request<DocumentT>("POST", `/api/documents/${id}/versions`, { form }),
  verify: (id: number, v: number) => request<VerifyT>("GET", `/api/documents/${id}/versions/${v}/verify`),
  async download(id: number, v: number, fallbackName: string) {
    const res = await request<Response>("GET", `/api/documents/${id}/versions/${v}/download`, { raw: true });
    const cd = res.headers.get("content-disposition") ?? "";
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    saveBlob(await res.blob(), m ? decodeURIComponent(m[1]) : fallbackName);
  },

  summarizeVersion: (id: number, v: number) => request<{ summary: string | null; available: boolean }>("POST", `/api/documents/${id}/versions/${v}/summary`),
  classificationFeedback: (id: number, correct_type: string) => request<void>("POST", `/api/documents/${id}/classification-feedback`, { body: { correct_type } }),
  summarizeCase: (id: number) => request<CaseSummary>("POST", `/api/cases/${id}/summary`),
  ledgerStatus: () => request<LedgerStatus>("GET", "/api/ledger/status"),
  search: (p: Record<string, string | undefined>) => request<SearchResult>("GET", `/api/search${qs(p)}`),

  audit: (p: Record<string, string | number | undefined>) => request<{ total: number; items: AuditEntry[] }>("GET", `/api/audit${qs(p)}`),
  auditVerify: () => request<ChainCheck>("GET", "/api/audit/verify"),
  auditAnchor: () => request<{ audit_id?: number; tx_id?: string; skipped?: string }>("POST", "/api/audit/anchor"),
  async auditExport(p: Record<string, string | undefined>) {
    const res = await request<Response>("GET", `/api/audit/export${qs(p)}`, { raw: true });
    saveBlob(await res.blob(), "sdms-audit-export.csv");
  },
  blocks: (p: { offset?: number; limit?: number; kind?: string }) => request<{ total: number; items: Block[] }>("GET", `/api/ledger/blocks${qs(p)}`),
  ledgerVerify: () => request<ChainCheck>("GET", "/api/ledger/verify"),
};

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as any;
    if (e.status === 409 && d?.report?.reasons) return `${e.message}: ${d.report.reasons.join("; ")}`;
    return e.message;
  }
  return e instanceof Error ? e.message : "Unexpected error";
}

export const DOC_TYPES = [
  "fir", "police_report", "investigation_record", "witness_statement", "charge_sheet", "court_filing",
  "evidence_record", "forensic_report", "legal_notice", "judgment", "medical_report", "arrest_warrant", "other",
] as const;
const ACRONYMS: Record<string, string> = { fir: "FIR" };
export const label = (s: string) => ACRONYMS[s] ?? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
export const shortHash = (h: string | null | undefined, n = 10) => (h ? `${h.slice(0, n)}…${h.slice(-4)}` : "—");
export const fmtTime = (ts: string) => new Date(ts).toLocaleString();
export const fmtSize = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`);
