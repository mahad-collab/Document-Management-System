"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, EmptyState, PrimaryButton, SecondaryButton, TextInput, Label, Badge } from "@/components/ui";
import type { AppUser, RoleName } from "@/lib/types";

const ROLES: { value: RoleName; label: string }[] = [
  { value: "super_admin", label: "Super Admin (org-wide)" },
  { value: "department_admin", label: "Department Admin" },
  { value: "department_user", label: "Department User" },
  { value: "read_only", label: "Read Only" },
];

const ROLE_LABEL: Record<RoleName, string> = {
  super_admin: "Super Admin",
  department_admin: "Dept. Admin",
  department_user: "Dept. User",
  read_only: "Read Only",
};

function CreateUserCard({ onCreated }: { onCreated: () => void }) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createUser({ email, display_name: displayName, job_title: jobTitle || undefined });
      setEmail("");
      setDisplayName("");
      setJobTitle("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create user");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <h2 className="mb-1 text-sm font-semibold text-slate-900 dark:text-slate-100">Create a user</h2>
      <p className="mb-4 text-xs text-slate-400 dark:text-slate-500">
        Pre-provisions an account before their first sign-in — useful so you can grant a role right away. No
        password is set; the account links to their real Entra ID identity automatically the first time they log
        in with this email.
      </p>
      {error && <ErrorBanner message={error} />}
      <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-4">
        <div>
          <Label>Email</Label>
          <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={320} />
        </div>
        <div>
          <Label>Display name</Label>
          <TextInput value={displayName} onChange={(e) => setDisplayName(e.target.value)} required maxLength={200} />
        </div>
        <div>
          <Label>Job title (optional)</Label>
          <TextInput value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} maxLength={200} />
        </div>
        <div className="flex items-end">
          <PrimaryButton type="submit" disabled={submitting || !email || !displayName}>
            {submitting ? "Creating…" : "Create user"}
          </PrimaryButton>
        </div>
      </form>
    </Card>
  );
}

function EditUserRow({
  user,
  onSaved,
  onCancel,
}: {
  user: AppUser;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [jobTitle, setJobTitle] = useState(user.job_title ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.updateUser(user.id, { display_name: displayName, job_title: jobTitle || undefined });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update user");
      setSaving(false);
    }
  }

  return (
    <tr className="border-b border-slate-100 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
      <td className="py-2 pr-4" colSpan={5}>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <Label>Display name</Label>
            <TextInput value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={200} />
          </div>
          <div>
            <Label>Job title</Label>
            <TextInput value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} maxLength={200} />
          </div>
          <PrimaryButton onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-xs">
            {saving ? "Saving…" : "Save"}
          </PrimaryButton>
          <SecondaryButton onClick={onCancel} disabled={saving} className="px-3 py-1.5 text-xs">
            Cancel
          </SecondaryButton>
          {error && <span className="text-xs text-red-700 dark:text-red-400">{error}</span>}
        </div>
      </td>
    </tr>
  );
}

function UsersBody() {
  const { user, departments, selectedDepartmentId } = useApp();
  const [users, setUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [targetUserId, setTargetUserId] = useState("");
  const [role, setRole] = useState<RoleName>("department_user");
  const [assignDeptId, setAssignDeptId] = useState(selectedDepartmentId ?? "");
  const [assigning, setAssigning] = useState(false);

  const scopeDeptId = user!.is_super_admin ? undefined : selectedDepartmentId ?? undefined;

  async function loadUsers() {
    if (!user!.is_super_admin && !scopeDeptId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setUsers(await api.listUsers(scopeDeptId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
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
      await loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to assign role");
    } finally {
      setAssigning(false);
    }
  }

  async function handleRemoveRole(assignmentId: string) {
    setBusyKey(`role-${assignmentId}`);
    setError(null);
    setSuccess(null);
    try {
      await api.removeRoleAssignment(assignmentId);
      await loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove role");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleToggleActive(target: AppUser) {
    setBusyKey(`active-${target.id}`);
    setError(null);
    try {
      await api.updateUser(target.id, { is_active: !target.is_active });
      await loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update user");
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDelete(target: AppUser) {
    if (!confirm(`Delete ${target.display_name} (${target.email})? This can't be undone from the UI.`)) return;
    setBusyKey(`delete-${target.id}`);
    setError(null);
    try {
      await api.deleteUser(target.id);
      await loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete user");
    } finally {
      setBusyKey(null);
    }
  }

  if (!user!.is_super_admin && !selectedDepartmentId) {
    return <EmptyState message="No department selected — pick one from the top bar." />;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Users</h1>

      {error && <ErrorBanner message={error} />}
      {success && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300">
          {success}
        </div>
      )}

      {user!.is_super_admin && <CreateUserCard onCreated={loadUsers} />}

      <Card>
        <h2 className="mb-4 text-sm font-semibold text-slate-900 dark:text-slate-100">Assign a role</h2>
        <form onSubmit={handleAssign} className="grid gap-4 sm:grid-cols-4">
          <div>
            <Label>User</Label>
            <select
              value={targetUserId}
              onChange={(e) => setTargetUserId(e.target.value)}
              required
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
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
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
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
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
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
        <h2 className="mb-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
          {user!.is_super_admin ? "All users" : "Users in this department"}
        </h2>
        {loading ? (
          <p className="text-sm text-slate-400 dark:text-slate-500">Loading…</p>
        ) : users.length === 0 ? (
          <EmptyState message="No users found." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  <th className="py-2 pr-4">User</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Roles</th>
                  {user!.is_super_admin && <th className="py-2 pr-4"></th>}
                </tr>
              </thead>
              <tbody>
                {users.map((u) =>
                  editingId === u.id ? (
                    <EditUserRow
                      key={u.id}
                      user={u}
                      onSaved={() => {
                        setEditingId(null);
                        loadUsers();
                      }}
                      onCancel={() => setEditingId(null)}
                    />
                  ) : (
                    <tr key={u.id} className="border-b border-slate-100 align-top dark:border-slate-800">
                      <td className="py-2 pr-4">
                        <div className="font-medium text-slate-900 dark:text-slate-100">{u.display_name}</div>
                        <div className="text-xs text-slate-400 dark:text-slate-500">{u.email}</div>
                        {u.job_title && <div className="text-xs text-slate-400 dark:text-slate-500">{u.job_title}</div>}
                      </td>
                      <td className="py-2 pr-4">
                        <Badge color={u.is_active ? "green" : "slate"}>{u.is_active ? "Active" : "Disabled"}</Badge>
                      </td>
                      <td className="py-2 pr-4">
                        {(u.roles ?? []).length === 0 ? (
                          <span className="text-xs text-slate-400 dark:text-slate-500">No roles yet</span>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {u.roles.map((r) => (
                              <span
                                key={r.id}
                                className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                              >
                                {ROLE_LABEL[r.role]}
                                {r.department_name ? ` · ${r.department_name}` : ""}
                                <button
                                  type="button"
                                  onClick={() => handleRemoveRole(r.id)}
                                  disabled={busyKey === `role-${r.id}`}
                                  title="Remove this role"
                                  className="ml-0.5 text-slate-400 hover:text-red-600 disabled:opacity-50 dark:text-slate-500 dark:hover:text-red-400"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      {user!.is_super_admin && (
                        <td className="py-2 pr-4">
                          <div className="flex gap-2">
                            <SecondaryButton onClick={() => setEditingId(u.id)} className="px-3 py-1 text-xs">
                              Edit
                            </SecondaryButton>
                            <SecondaryButton
                              onClick={() => handleToggleActive(u)}
                              disabled={busyKey === `active-${u.id}` || u.id === user!.id}
                              className="px-3 py-1 text-xs"
                              title={u.id === user!.id ? "You cannot deactivate your own account" : undefined}
                            >
                              {u.is_active ? "Deactivate" : "Reactivate"}
                            </SecondaryButton>
                            <SecondaryButton
                              onClick={() => handleDelete(u)}
                              disabled={busyKey === `delete-${u.id}` || u.id === user!.id}
                              className="px-3 py-1 text-xs text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
                              title={u.id === user!.id ? "You cannot delete your own account" : undefined}
                            >
                              Delete
                            </SecondaryButton>
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                )}
              </tbody>
            </table>
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
