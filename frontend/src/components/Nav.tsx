"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useApp } from "@/lib/app-context";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/documents", label: "Documents" },
  { href: "/search", label: "Search" },
  { href: "/departments", label: "Departments", superAdminOnly: true },
  { href: "/users", label: "Users" },
  { href: "/audit-logs", label: "Audit Logs" },
];

export default function Nav() {
  const { user, departments, selectedDepartmentId, setSelectedDepartmentId, logout } = useApp();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) {
    return (
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-4 sm:px-6">
          <Image src="/Puma_Energy_Logo.jpg" alt="Puma Energy" width={132} height={24} priority />
          <span className="text-lg font-semibold text-slate-900">Puma DMS</span>
        </div>
      </header>
    );
  }

  const visibleLinks = LINKS.filter((l) => !l.superAdminOnly || user.is_super_admin);

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
        <Link href="/dashboard" className="flex shrink-0 items-center gap-2">
          <Image src="/Puma_Energy_Logo.jpg" alt="Puma Energy" width={99} height={18} />
          <span className="text-lg font-semibold text-slate-900">Puma DMS</span>
        </Link>

        <nav className="flex flex-wrap gap-1 text-sm">
          {visibleLinks.map((l) => {
            const active = pathname === l.href;
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                  active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {departments.length > 0 && (
            <select
              value={selectedDepartmentId ?? ""}
              onChange={(e) => setSelectedDepartmentId(e.target.value || null)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
              title="Active department — most pages act within this department"
            >
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
          <span className="hidden text-sm text-slate-500 sm:inline">
            {user.display_name}
            {user.is_super_admin && (
              <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
                Super Admin
              </span>
            )}
          </span>
          <button
            onClick={async () => {
              await logout();
              router.push("/");
            }}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}
