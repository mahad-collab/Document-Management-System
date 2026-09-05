"use client";

import { useEffect } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useApp, loginUrl } from "@/lib/app-context";
import { Spinner } from "@/components/ui";

export default function HomePage() {
  const { user, loadingUser } = useApp();
  const router = useRouter();

  useEffect(() => {
    if (!loadingUser && user) router.replace("/dashboard");
  }, [loadingUser, user, router]);

  if (loadingUser) return <Spinner />;
  if (user) return <Spinner />; // brief flash while redirecting

  return (
    <div className="mx-auto mt-24 max-w-md text-center">
      <Image src="/Puma_Energy_Logo.jpg" alt="Puma Energy" width={220} height={40} className="mx-auto" priority />
      <h1 className="mt-4 text-2xl font-semibold text-slate-900">Puma DMS</h1>
      <p className="mt-2 text-sm text-slate-500">
        Document Management System — Puma Energy Pakistan
      </p>
      <a
        href={loginUrl()}
        className="mt-8 inline-block rounded-md bg-slate-900 px-6 py-3 text-sm font-medium text-white hover:bg-slate-700"
      >
        Sign in with Microsoft
      </a>
      <p className="mt-4 text-xs text-slate-400">
        You&rsquo;ll be redirected to your organization&rsquo;s Microsoft login.
      </p>
    </div>
  );
}
