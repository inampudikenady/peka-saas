"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { usePlatformUser } from "@/hooks/use-platform-user";

export default function PlatformDashboardRedirect() {
  const router = useRouter();
  const { user, error } = usePlatformUser();

  useEffect(() => {
    if (user) router.replace(user.role === "platform_admin" ? "/platform/tenants" : "/platform/overview");
  }, [router, user]);

  return <main className="p-8 text-sm text-slate-500">{error || "Redirecting…"}</main>;
}
