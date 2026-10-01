export type Role = "officer" | "admin" | "auditor" | "forensic" | "judge" | "prosecutor" | "defence";
export type Rank = "officer" | "station_head" | "superintendent" | "district_court" | "high_court" | "system";
export const SHARE_ROLES: Role[] = ["forensic", "judge", "prosecutor", "defence"];
export const ROLE_LABEL: Record<Role, string> = {
  officer: "Police officer", admin: "Administrator", auditor: "Auditor", forensic: "Forensic lab", judge: "Judge",
  prosecutor: "Public prosecutor", defence: "Defence lawyer",
};
export const STAGE_LABEL: Record<string, string> = {
  under_investigation: "Under investigation", charge_sheeted: "Charge-sheeted", in_trial: "In trial", judgment_delivered: "Judgment delivered",
};
export const APPROVAL_LABEL: Record<string, string> = {
  not_required: "No approval needed", pending: "Awaiting station head's approval", approved: "Approved", returned: "Returned for correction",
};

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  rank: Rank;
  station_id: number | null;
  station_name: string | null;
  district_id: number | null;
  district_name: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  must_change_password: boolean;
}

export interface Party { name: string; role: string }
export interface Assignee { user_id: number; username: string; full_name: string }
export interface Share { user_id: number; username: string; full_name: string; role: string; shared_by: string; created_at: string; expires_at: string | null; expired: boolean }
export interface CaseT {
  id: number; case_number: string; fir_number: string | null; title: string; case_type: string | null;
  description: string | null; status: string; stage: string; station_id: number; station_name: string | null; created_at: string;
  parties: Party[]; assignees: Assignee[]; shares: Share[]; document_count: number | null; can_edit: boolean; can_reopen: boolean;
}

/** Roles/ranks that can open case & document content (view, download, verify) — never "admin" or "auditor". */
export const hasContentAccess = (u: User | null) => !!u && (u.role === "officer" || SHARE_ROLES.includes(u.role));
/** Roles that file documents into a case (forensic, prosecutor and defence only into cases shared with them). */
export const canFile = (u: User | null) => !!u && ["officer", "forensic", "prosecutor", "defence"].includes(u.role);
/** Parties who rely on a document as evidence: they see its chain of custody and can print its certificate. */
export const canSeeCustody = (u: User | null) => !!u && ["officer", "judge", "prosecutor"].includes(u.role);
export const isApprover = (u: User | null) => u?.role === "officer" && (u.rank === "station_head" || u.rank === "superintendent");
export const isSystemAdmin = (u: User | null) => u?.role === "admin" && u.rank === "system";
/** Only a plain, assigned officer can upload/version/summarise/create cases — senior officers included, reviewers not. */
/** A judge whose court has jurisdiction (district/high court) can record the verdict; a per-case-share judge cannot. */
export const canDecide = (u: User | null) => u?.role === "judge" && (u.rank === "district_court" || u.rank === "high_court");
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
  created_by: string | null; created_by_role: string | null; case_status: string;
  approval_status: string; approval_by: string | null; approval_at: string | null; approval_note: string | null; approved_version: number | null;
}
/** A document is changed only by the department that filed it, and only while its case is open. */
export const canEditDocument = (u: User | null, d: DocumentT) =>
  !!u && d.case_status === "open" &&
  ((u.role === "officer" && d.created_by_role === "officer") ||
   (["forensic", "prosecutor", "defence"].includes(u.role) && d.created_by === u.username));
export interface EditEntry {
  id: number; ts: string; kind: "case" | "document" | "version" | "approval"; editor: string | null; editor_name: string | null;
  editor_role: string | null; document_id: number | null; document_title: string | null; version_no: number | null;
  reason: string | null; changes: { field: string; old: string | null; new: string | null }[]; verified: boolean; problem: string | null;
}
export interface DiffT {
  from_version: number; to_version: number; available: boolean; note: string | null; added: number; removed: number;
  truncated: boolean; lines: { op: "+" | "-" | " " | "@"; text: string }[];
}
export interface VerifyT {
  document_id: number; version_no: number; status: "verified" | "tampered"; reasons: string[];
  stored_sha256: string; recomputed_sha256: string | null; ledger_sha256: string | null;
  ledger_tx_id: string | null; ledger_block: number | null;
}
export interface CustodyEntry { id: number; ts: string; actor: string | null; actor_role: string | null; action: string; label: string; outcome: string; version_no: number | null }
export interface SignatureT { signer: string; signer_name: string; signer_role: string; signer_rank: string; signed_at: string; valid: boolean; problems: string[]; fingerprint: string }
export interface AlertT { id: number; ts: string; action: string; label: string; unread: boolean; actor: string | null; case_number: string | null; case_id: number | null; document_id: number | null; reasons: string[] }
export interface ApprovalItem { document_id: number; title: string; doc_type: string; case_id: number; case_number: string; filed_by: string; filed_at: string }
export interface DashboardT {
  cases: { open: number; closed: number; by_stage: Record<string, number> } | null;
  recent_cases?: { id: number; case_number: string; title: string; status: string; stage: string }[];
  documents: number | null;
  approvals: ApprovalItem[];
  returned: { document_id: number; title: string; case_id: number; note: string | null; by: string | null; at: string | null }[];
  expiring_shares: { case_id: number; case_number: string; username: string; role: string; expires_at: string }[];
  alerts: AlertT[]; alerts_unread: number;
}
export interface CertificateT {
  certificate_no: string; certificate_sha256: string; issued_at: string;
  issued_by: { name: string; username: string; role: string; rank: string; station: string | null };
  case: { case_number: string; title: string; fir_number: string | null; station: string | null; status: string; stage: string };
  document: { id: number; uid: string; title: string; doc_type: string; version_no: number; versions: number; filename: string; content_type: string; size: number; uploaded_by: string; uploaded_by_username: string; uploaded_at: string; change_note: string | null };
  integrity: { status: string; sha256: string; recomputed_sha256: string; ledger_sha256: string; ledger_tx_id: string; ledger_block: number | null; ledger: string; checked_at: string };
  approval: { status: string; by: string | null; at: string | null; version: number | null };
  signatures: SignatureT[]; custody: CustodyEntry[];
  system: { name: string; hash: string; encryption: string; audit: string };
}
export interface Org { districts: { id: number; code: string; name: string }[]; stations: { id: number; code: string; name: string; district_id: number | null }[] }
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
  editCase: (id: number, b: { title?: string; fir_number?: string; case_type?: string; description?: string; parties?: Party[]; stage?: string; reason: string }) =>
    request<CaseT>("PATCH", `/api/cases/${id}`, { body: b }),
  reopen: (id: number, reason: string) => request<CaseT>("POST", `/api/cases/${id}/reopen`, { body: { reason } }),
  caseHistory: (id: number) => request<EditEntry[]>("GET", `/api/cases/${id}/history`),
  assign: (caseId: number, userId: number) => request<CaseT>("POST", `/api/cases/${caseId}/assignments`, { body: { user_id: userId } }),
  unassign: (caseId: number, userId: number) => request<CaseT>("DELETE", `/api/cases/${caseId}/assignments/${userId}`),
  share: (caseId: number, userId: number, days?: number) =>
    request<CaseT>("POST", `/api/cases/${caseId}/shares`, { body: { user_id: userId, ...(days ? { days } : {}) } }),
  unshare: (caseId: number, userId: number) => request<CaseT>("DELETE", `/api/cases/${caseId}/shares/${userId}`),

  users: () => request<User[]>("GET", "/api/users"),
  reviewers: () => request<User[]>("GET", "/api/users/reviewers"),
  createUser: (b: { username: string; full_name: string; password: string; role?: Role; rank?: Rank; station_id?: number; district_id?: number }) =>
    request<User>("POST", "/api/users", { body: b }),
  resetPassword: (id: number) => request<{ username: string; temporary_password: string }>("POST", `/api/users/${id}/reset-password`),
  org: () => request<Org>("GET", "/api/users/org"),
  setActive: (id: number, is_active: boolean, rank: Rank) => request<User>("PATCH", `/api/users/${id}`, { body: { is_active, rank } }),
  resetMfa: (id: number) => request<User>("POST", `/api/users/${id}/reset-mfa`),
  unlock: (id: number) => request<User>("POST", `/api/users/${id}/unlock`),

  documents: (caseId: number) => request<DocumentT[]>("GET", `/api/cases/${caseId}/documents`),
  document: (id: number) => request<DocumentT>("GET", `/api/documents/${id}`),
  verdict: (caseId: number, b: { outcome: string; reasoning: string; sentence?: string }) =>
    request<DocumentT>("POST", `/api/cases/${caseId}/verdict`, { body: b }),
  upload: (caseId: number, form: FormData) => request<DocumentT>("POST", `/api/cases/${caseId}/documents`, { form }),
  uploadVersion: (id: number, form: FormData) => request<DocumentT>("POST", `/api/documents/${id}/versions`, { form }),
  editDocument: (id: number, b: { title?: string; description?: string; reason: string }) =>
    request<DocumentT>("PATCH", `/api/documents/${id}`, { body: b }),
  /** The verified file as a blob, for the in-browser viewer (recorded as "viewed", not "downloaded"). */
  async viewBlob(id: number, v: number) {
    const res = await request<Response>("GET", `/api/documents/${id}/versions/${v}/download?inline=true`, { raw: true });
    return res.blob();
  },
  extractedText: (id: number, v: number) => request<{ available: boolean; text: string; method: string | null; language: string | null }>("GET", `/api/documents/${id}/versions/${v}/text`),
  custody: (id: number) => request<CustodyEntry[]>("GET", `/api/documents/${id}/custody`),
  certificate: (id: number, v: number) => request<CertificateT>("GET", `/api/documents/${id}/versions/${v}/certificate`),
  signatures: (id: number, v: number) => request<{ can_sign: boolean; signatures: SignatureT[] }>("GET", `/api/documents/${id}/versions/${v}/signatures`),
  sign: (id: number, v: number, password: string) => request<SignatureT>("POST", `/api/documents/${id}/versions/${v}/sign`, { body: { password } }),
  decide: (id: number, decision: "approve" | "return", note?: string) =>
    request<DocumentT>("POST", `/api/documents/${id}/approval`, { body: { decision, note } }),
  approvals: () => request<ApprovalItem[]>("GET", "/api/approvals"),
  dashboard: () => request<DashboardT>("GET", "/api/dashboard"),
  alerts: () => request<{ unread: number; items: AlertT[] }>("GET", "/api/alerts"),
  alertsSeen: () => request<void>("POST", "/api/alerts/seen"),
  documentHistory: (id: number) => request<EditEntry[]>("GET", `/api/documents/${id}/history`),
  versionDiff: (id: number, v: number) => request<DiffT>("GET", `/api/documents/${id}/versions/${v}/diff`),
  /** The verified content of a text version, for the in-browser editor (the server refuses if the file was tampered with). */
  async versionText(id: number, v: number) {
    const res = await request<Response>("GET", `/api/documents/${id}/versions/${v}/download`, { raw: true });
    return res.text();
  },
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
