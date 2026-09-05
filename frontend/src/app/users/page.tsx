"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, EmptyState, PrimaryButton, Label, Badge } from "@/components/ui";
import type { AppUser, RoleName } from "@/lib/types";

const ROLES: { value: RoleName; label: string }[] = [
  { value: "super_admin", label: "Super Admin (org-wide)" },
  { value: "department_admin", label: "Department Admin" },
  { value: "department_user", label: "Department User" },
  { value: "read_only", label: "Read Only" },
];

function UsersBody() {
  const { user, departments, selectedDepartmentId } = useApp();
  const [users, setUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [targetUserId, setTargetUserId] = useState("");
  const [role, setRole] = useState<RoleName>("department_user");
  const [assignDeptId, setAssignDeptId] = useState(selectedDepartmentId ?? "");
  const [assigning, setAssigning] = useState(false);

  const scopeDeptId = user!.is_super_admin ? undefined : selectedDepartmentId ?? undefined;

  useEffect(() => {
    if (!user!.is_super_admin && !scopeDeptId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .listUsers(scopeDeptId)
      .then(setUsers)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load users"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeDeptId]);

  async function handleAssign(e: React.FormEvent) {
    e.preventDefault();
    setAssigning(true);
    setError(null);
    setSuccess(null);
    try {
      await api.assignRole({
        user_id: targetUserId,
        role,
        department_id: role === "super_admin" ? undefined : assignDeptId || undefined,
      });
      setSuccess("Role assigned.");
      setTargetUserId("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to assign role");
    } finally {
      setAssigning(false);
    }
  }

  if (!user!.is_super_admin && !selectedDepartmentId) {
    return <EmptyState message="No department selected — pick one from the top bar." />;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">Users</h1>

      {error && <ErrorBanner message={error} />}
      {success && <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">{success}</div>}

      <Card>
        <h2 className="mb-4 text-sm font-semibold text-slate-900">Assign a role</h2>
        <form onSubmit={handleAssign} className="grid gap-4 sm:grid-cols-4">
          <div>
            <Label>User</Label>
            <select
              value={targetUserId}
              onChange={(e) => setTargetUserId(e.target.value)}
              required
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="" disabled>
                Select a user
              </option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label>Role</Label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as RoleName)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {ROLES.filter((r) => user!.is_super_admin || r.value !== "super_admin").map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          {role !== "super_admin" && (
            <div>
              <Label>Department</Label>
              <select
                value={assignDeptId}
                onChange={(e) => setAssignDeptId(e.target.value)}
                required
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="" disabled>
                  Select a department
                </option>
                {(user!.is_super_admin ? departments : departments.filter((d) => d.id === selectedDepartmentId)).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-end">
            <PrimaryButton type="submit" disabled={assigning || !targetUserId}>
              {assigning ? "Assigning…" : "Assign role"}
            </PrimaryButton>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="mb-4 text-sm font-semibold text-slate-900">
          {user!.is_super_admin ? "All users" : "Users in this department"}
        </h2>
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : users.length === 0 ? (
          <EmptyState message="No users found." />
        ) : (
          <div className="space-y-2">
            {users.map((u) => (
              <div key={u.id} className="flex items-center justify-between rounded-md border border-slate-200 px-4 py-2 text-sm">
                <div>
                  <div className="font-medium text-slate-900">{u.display_name}</div>
                  <div className="text-xs text-slate-400">{u.email}</div>
                </div>
                <Badge color={u.is_active ? "green" : "slate"}>{u.is_active ? "Active" : "Disabled"}</Badge>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export default function UsersPage() {
  return (
    <RequireAuth>
      <UsersBody />
    </RequireAuth>
  );
}
