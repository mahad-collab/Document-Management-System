"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, PrimaryButton, SecondaryButton, TextInput, Label, Badge } from "@/components/ui";

function DepartmentsBody() {
  const { user, departments, refreshDepartments, loadingDepartments } = useApp();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  if (!user?.is_super_admin) {
    return <ErrorBanner message="Only Super Admin can manage departments." />;
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createDepartment({ name, code, description: description || undefined });
      setName("");
      setCode("");
      setDescription("");
      await refreshDepartments();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create department");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleActive(id: string, isActive: boolean) {
    setBusyId(id);
    setError(null);
    try {
      if (isActive) await api.disableDepartment(id);
      else await api.reactivateDepartment(id);
      await refreshDepartments();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">Departments</h1>
      {error && <ErrorBanner message={error} />}

      <Card>
        <h2 className="mb-4 text-sm font-semibold text-slate-900">Create a department</h2>
        <form onSubmit={handleCreate} className="grid gap-4 sm:grid-cols-3">
          <div>
            <Label>Name</Label>
            <TextInput value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={100} />
          </div>
          <div>
            <Label>Code (e.g. FIN)</Label>
            <TextInput
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              required
              pattern="[A-Z0-9_]+"
              minLength={2}
              maxLength={20}
              title="Uppercase letters, digits, underscores"
            />
          </div>
          <div>
            <Label>Description (optional)</Label>
            <TextInput value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
          </div>
          <div className="sm:col-span-3">
            <PrimaryButton type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create department"}
            </PrimaryButton>
            <p className="mt-2 text-xs text-slate-400">
              Creates a matching folder in SharePoint immediately — if that call fails, no department is created.
            </p>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="mb-4 text-sm font-semibold text-slate-900">All departments</h2>
        {loadingDepartments ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : departments.length === 0 ? (
          <p className="text-sm text-slate-400">No departments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Code</th>
                  <th className="py-2 pr-4">SharePoint folder</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4"></th>
                </tr>
              </thead>
              <tbody>
                {departments.map((d) => (
                  <tr key={d.id} className="border-b border-slate-100">
                    <td className="py-2 pr-4 font-medium text-slate-900">{d.name}</td>
                    <td className="py-2 pr-4 text-slate-600">{d.code}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-400">
                      {d.sharepoint_item_id ? d.sharepoint_item_id.slice(0, 16) + "…" : "—"}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge color={d.is_active ? "green" : "slate"}>{d.is_active ? "Active" : "Disabled"}</Badge>
                    </td>
                    <td className="py-2 pr-4">
                      <SecondaryButton
                        onClick={() => toggleActive(d.id, d.is_active)}
                        disabled={busyId === d.id}
                        className="px-3 py-1 text-xs"
                      >
                        {d.is_active ? "Disable" : "Reactivate"}
                      </SecondaryButton>
                    </td>
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

export default function DepartmentsPage() {
  return (
    <RequireAuth>
      <DepartmentsBody />
    </RequireAuth>
  );
}
