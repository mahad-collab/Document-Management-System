// Mirrors the Pydantic response models in backend/app/*/schemas.py.
// Kept as one file since the backend doesn't publish an OpenAPI-generated
// client — these are hand-synced against the schemas, not auto-generated.

export type UUID = string;

export interface CurrentUserInfo {
  id: UUID;
  email: string;
  display_name: string;
  is_super_admin: boolean;
  departments: UUID[];
}

export interface Department {
  id: UUID;
  name: string;
  code: string;
  description: string | null;
  is_active: boolean;
  sharepoint_item_id: string | null;
}

export interface Folder {
  id: UUID;
  name: string;
  department_id: UUID;
  parent_id: UUID | null;
  sharepoint_item_id: string;
  is_archived: boolean;
}

export type OCRStatus = "pending" | "processing" | "completed" | "failed" | "skipped";

export interface DocumentItem {
  id: UUID;
  name: string;
  department_id: UUID;
  folder_id: UUID;
  document_type: string | null;
  document_number: string | null;
  document_date: string | null;
  description: string | null;
  uploaded_by: UUID;
  current_version_number: number;
  file_size: number;
  file_type: string;
  ocr_status: OCRStatus;
  is_deleted: boolean;
  created_at: string;
}

export interface DocumentVersion {
  id: UUID;
  version_number: number;
  sharepoint_version_label: string;
  uploaded_by: UUID;
  change_description: string | null;
  file_size: number;
  created_at: string;
}

export type RoleName = "super_admin" | "department_admin" | "department_user" | "read_only";

export interface AppUser {
  id: UUID;
  email: string;
  display_name: string;
  is_active: boolean;
}

export interface RoleAssignment {
  id: UUID;
  user_id: UUID;
  role_id: UUID;
  department_id: UUID | null;
}

export type AuditResult = "success" | "failure";

export interface AuditLogEntry {
  id: UUID;
  user_id: UUID | null;
  action: string;
  department_id: UUID | null;
  document_id: UUID | null;
  result: AuditResult;
  details: string | null;
  created_at: string;
}

export interface DepartmentDocumentCount {
  department_id: UUID;
  department_name: string;
  document_count: number;
}

export interface OCRStatusBreakdown {
  status: OCRStatus;
  count: number;
}

export interface RecentDocumentSummary {
  id: UUID;
  name: string;
  department_id: UUID;
  created_at: string;
}

export interface OrgWideDashboard {
  total_documents: number;
  total_users: number;
  total_departments: number;
  documents_uploaded_today: number;
  pending_ocr: number;
  ocr_failures: number;
  archived_folders: number;
  deleted_documents: number;
  total_storage_bytes: number;
  department_document_counts: DepartmentDocumentCount[];
  ocr_status_breakdown: OCRStatusBreakdown[];
  recent_uploads: RecentDocumentSummary[];
  recent_deleted: RecentDocumentSummary[];
}

export interface DepartmentDashboard {
  department_id: UUID;
  total_documents: number;
  documents_uploaded_today: number;
  pending_ocr: number;
  recent_uploads: RecentDocumentSummary[];
}

export type Dashboard = OrgWideDashboard | DepartmentDashboard;

export function isOrgWideDashboard(d: Dashboard): d is OrgWideDashboard {
  return (d as OrgWideDashboard).total_users !== undefined;
}
