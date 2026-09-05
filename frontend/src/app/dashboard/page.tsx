"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, Spinner, Badge, formatBytes, formatDate } from "@/components/ui";
import type { Dashboard } from "@/lib/types";
import { isOrgWideDashboard } from "@/lib/types";
import Link from "next/link";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
    </Card>
  );
}

function DashboardBody() {
  const { user, selectedDepartmentId, selectedDepartment } = useApp();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [orgWide, setOrgWide] = useState(user!.is_super_admin);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const deptParam = orgWide ? undefined : selectedDepartmentId ?? undefined;
    if (!orgWide && !deptParam) {
      setLoading(false);
      return;
    }
    api
      .dashboard(deptParam)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Failed to load dashboard"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [orgWide, selectedDepartmentId]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-900">
          Dashboard {!orgWide && selectedDepartment && <span className="text-slate-400">— {selectedDepartment.name}</span>}
        </h1>
        {user!.is_super_admin && (
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
            <button
              onClick={() => setOrgWide(true)}
              className={`rounded px-3 py-1 ${orgWide ? "bg-slate-900 text-white" : "text-slate-600"}`}
            >
              Org-wide
            </button>
            <button
              onClick={() => setOrgWide(false)}
              className={`rounded px-3 py-1 ${!orgWide ? "bg-slate-900 text-white" : "text-slate-600"}`}
            >
              This department
            </button>
          </div>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && <Spinner />}

      {!loading && !error && !orgWide && !selectedDepartmentId && (
        <div className="rounded-md border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-400">
          No department selected — pick one from the top bar.
        </div>
      )}

      {!loading && data && isOrgWideDashboard(data) && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <Stat label="Documents" value={data.total_documents} />
            <Stat label="Users" value={data.total_users} />
            <Stat label="Departments" value={data.total_departments} />
            <Stat label="Uploaded today" value={data.documents_uploaded_today} />
            <Stat label="Pending OCR" value={data.pending_ocr} />
            <Stat label="OCR failures" value={data.ocr_failures} />
            <Stat label="Archived folders" value={data.archived_folders} />
            <Stat label="Deleted documents" value={data.deleted_documents} />
            <Stat label="Total storage" value={formatBytes(data.total_storage_bytes)} />
          </div>

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-slate-900">Documents by department</h2>
            <div className="space-y-2">
              {data.department_document_counts.map((d) => (
                <div key={d.department_id} className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">{d.department_name}</span>
                  <span className="font-medium text-slate-900">{d.document_count}</span>
                </div>
              ))}
            </div>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-slate-900">Recent uploads</h2>
              <RecentList items={data.recent_uploads} />
            </Card>
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-slate-900">Recently deleted</h2>
              <RecentList items={data.recent_deleted} />
            </Card>
          </div>
        </>
      )}

      {!loading && data && !isOrgWideDashboard(data) && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label="Documents" value={data.total_documents} />
            <Stat label="Uploaded today" value={data.documents_uploaded_today} />
            <Stat label="Pending OCR" value={data.pending_ocr} />
          </div>
          <Card>
            <h2 className="mb-3 text-sm font-semibold text-slate-900">Recent uploads</h2>
            <RecentList items={data.recent_uploads} />
          </Card>
        </>
      )}
    </div>
  );
}

function RecentList({ items }: { items: { id: string; name: string; created_at: string }[] }) {
  if (items.length === 0) return <p className="text-sm text-slate-400">Nothing yet.</p>;
  return (
    <ul className="space-y-2">
      {items.map((i) => (
        <li key={i.id} className="flex items-center justify-between text-sm">
          <Link href="/documents" className="truncate text-slate-700 hover:underline">
            {i.name}
          </Link>
          <Badge>{formatDate(i.created_at)}</Badge>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardBody />
    </RequireAuth>
  );
}
