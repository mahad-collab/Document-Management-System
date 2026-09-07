// Thin fetch wrapper around the FastAPI backend. Every call sends
// credentials so the browser attaches the DMS session cookie set during the
// Entra ID OAuth callback (see backend/app/auth/routes.py) — this is the
// "backend-for-frontend" pattern: this file never sees an Entra token,
// only the app's own signed session cookie.
import type {
  AppUser,
  AuditLogEntry,
  CurrentUserInfo,
  Dashboard,
  Department,
  DocumentItem,
  DocumentVersion,
  Folder,
  RoleAssignment,
  RoleName,
  UUID,
} from "./types";

// In the browser, talk to the backend on the SAME host the page itself was
// loaded from — this is what makes the app work identically whether you
// open it as localhost or as a LAN IP from another device: the browser's
// own address bar host is always reachable from that browser, whereas a
// hardcoded "localhost" wouldn't be (a phone hitting
// NEXT_PUBLIC_API_URL=http://localhost:8000 would try ITS OWN localhost,
// which has nothing running).
//
// Two backend instances run side by side in dev: plain HTTP on :8000 for
// localhost, and HTTPS on :8443 for LAN access — Entra ID's OAuth redirect
// URI must be either "https://" or exactly "http://localhost", so a LAN IP
// can only ever work over HTTPS (see backend/certs/ for the self-signed
// cert covering these LAN addresses). NEXT_PUBLIC_API_URL remains a
// fallback for server-side rendering, where there is no window.
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);

const API_URL =
  typeof window !== "undefined"
    ? LOCAL_HOSTS.has(window.location.hostname)
      ? `http://${window.location.hostname}:8000`
      : `https://${window.location.hostname}:8443`
    : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const loginUrl = () => `${API_URL}/auth/login`;

export const api = {
  // ---- Auth ----
  me: () => request<CurrentUserInfo>("/auth/me"),
  logout: () => request<{ detail: string }>("/auth/logout", { method: "POST" }),

  // ---- Departments ----
  listDepartments: (includeInactive = false) =>
    request<Department[]>(`/departments${qs({ include_inactive: includeInactive })}`),
  createDepartment: (payload: { name: string; code: string; description?: string }) =>
    request<Department>("/departments", { method: "POST", body: JSON.stringify(payload) }),
  renameDepartment: (id: UUID, payload: { name?: string; description?: string }) =>
    request<Department>(`/departments/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  disableDepartment: (id: UUID) => request<Department>(`/departments/${id}/disable`, { method: "POST" }),
  reactivateDepartment: (id: UUID) => request<Department>(`/departments/${id}/reactivate`, { method: "POST" }),

  // ---- Folders ----
  listFolders: (departmentId: UUID, parentId?: UUID | null) =>
    request<Folder[]>(`/folders${qs({ department_id: departmentId, parent_id: parentId ?? undefined })}`),
  createFolder: (payload: { name: string; department_id: UUID; parent_id?: UUID | null }) =>
    request<Folder>("/folders", { method: "POST", body: JSON.stringify(payload) }),
  archiveFolder: (id: UUID) => request<Folder>(`/folders/${id}/archive`, { method: "POST" }),

  // ---- Documents ----
  listDocuments: (params: { department_id: UUID; folder_id?: UUID; document_number?: string }) =>
    request<DocumentItem[]>(`/documents${qs(params)}`),
  getDocument: (id: UUID) => request<DocumentItem>(`/documents/${id}`),
  uploadDocument: (form: FormData) => request<DocumentItem>("/documents", { method: "POST", body: form }),
  downloadUrl: (id: UUID) => `${API_URL}/documents/${id}/download`,
  listVersions: (id: UUID) => request<DocumentVersion[]>(`/documents/${id}/versions`),
  uploadNewVersion: (id: UUID, form: FormData) =>
    request<DocumentItem>(`/documents/${id}/versions`, { method: "POST", body: form }),
  deleteDocument: (id: UUID) => request<DocumentItem>(`/documents/${id}/delete`, { method: "POST" }),
  restoreDocument: (id: UUID) => request<DocumentItem>(`/documents/${id}/restore`, { method: "POST" }),
  permanentDeleteDocument: (id: UUID) => request<void>(`/documents/${id}/permanent`, { method: "DELETE" }),

  // ---- Search ----
  search: (params: {
    department_id: UUID;
    q?: string;
    folder_id?: UUID;
    document_type?: string;
    document_date_from?: string;
    document_date_to?: string;
    uploader_id?: UUID;
    tags?: string;
    ocr_status?: string;
    include_deleted?: boolean;
  }) => request<DocumentItem[]>(`/search${qs(params)}`),

  // ---- Audit logs ----
  listAuditLogs: (params: {
    department_id?: UUID;
    user_id?: UUID;
    action?: string;
    document_id?: UUID;
    result?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
  }) => request<AuditLogEntry[]>(`/audit-logs${qs(params)}`),

  // ---- Users ----
  listUsers: (departmentId?: UUID) => request<AppUser[]>(`/users${qs({ department_id: departmentId })}`),
  createUser: (payload: { email: string; display_name: string; job_title?: string }) =>
    request<AppUser>("/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (id: UUID, payload: { display_name?: string; job_title?: string; is_active?: boolean }) =>
    request<AppUser>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (id: UUID) => request<void>(`/users/${id}`, { method: "DELETE" }),
  assignRole: (payload: { user_id: UUID; role: RoleName; department_id?: UUID | null }) =>
    request<RoleAssignment>("/users/role-assignments", { method: "POST", body: JSON.stringify(payload) }),
  removeRoleAssignment: (assignmentId: UUID) =>
    request<void>(`/users/role-assignments/${assignmentId}`, { method: "DELETE" }),

  // ---- Dashboard ----
  dashboard: (departmentId?: UUID) => request<Dashboard>(`/dashboard${qs({ department_id: departmentId })}`),

  // ---- OCR ----
  ocrStatus: (departmentId: UUID, status?: string) =>
    request<DocumentItem[]>(`/ocr/status${qs({ department_id: departmentId, status })}`),
  retryOcr: (id: UUID) => request<DocumentItem>(`/ocr/${id}/retry`, { method: "POST" }),
};
