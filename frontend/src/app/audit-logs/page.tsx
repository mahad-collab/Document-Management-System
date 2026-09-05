"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, EmptyState, Badge, formatDate } from "@/components/ui";
import type { AuditLogEntry } from "@/lib/types";

function AuditLogsBody() {
  const { user, selectedDepartmentId, departments } = useApp();
  const [orgWide, setOrgWide] = useState(user!.is_super_admin);
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const deptParam = orgWide ? undefined : selectedDepartmentId ?? undefined;
    if (!orgWide && !deptParam) {
      setLogs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .listAuditLogs({ department_id: deptParam, limit: 200 })
      .then(setLogs)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load audit logs"))
      .finally(() => setLoading(false));
  }, [orgWide, selectedDepartmentId]);

  const deptName = (id: string | null) => (id ? departments.find((d) => d.id === id)?.name ?? id.slice(0, 8) : "—");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-900">Audit Logs</h1>
        {user!.is_super_admin && (
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
            <button onClick={() => setOrgWide(true)} className={`rounded px-3 py-1 ${orgWide ? "bg-slate-900 text-white" : "text-slate-600"}`}>
              Org-wide
            </button>
            <button onClick={() => setOrgWide(false)} className={`rounded px-3 py-1 ${!orgWide ? "bg-slate-900 text-white" : "text-slate-600"}`}>
              This department
            </button>
          </div>
        )}
      </div>

      {error && <ErrorBanner message={error} />}

      <Card>
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : logs.length === 0 ? (
          <EmptyState message="No audit log entries match." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2 pr-4">Action</th>
                  <th className="py-2 pr-4">Department</th>
                  <th className="py-2 pr-4">Result</th>
                  <th className="py-2 pr-4">Details</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-slate-100 align-top">
                    <td className="whitespace-nowrap py-2 pr-4 text-slate-500">{formatDate(log.created_at)}</td>
                    <td className="py-2 pr-4 font-medium text-slate-900">{log.action}</td>
                    <td className="py-2 pr-4 text-slate-600">{deptName(log.department_id)}</td>
                    <td className="py-2 pr-4">
                      <Badge color={log.result === "success" ? "green" : "red"}>{log.result}</Badge>
                    </td>
                    <td className="py-2 pr-4 text-slate-500">{log.details ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function AuditLogsPage() {
  return (
    <RequireAuth>
      <AuditLogsBody />
    </RequireAuth>
  );
}
