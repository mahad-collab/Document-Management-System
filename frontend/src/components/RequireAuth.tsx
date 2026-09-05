"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/lib/app-context";
import { Spinner } from "@/components/ui";

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loadingUser } = useApp();
  const router = useRouter();

  useEffect(() => {
    if (!loadingUser && !user) router.replace("/");
  }, [loadingUser, user, router]);

  if (loadingUser || !user) return <Spinner />;
  return <>{children}</>;
}
