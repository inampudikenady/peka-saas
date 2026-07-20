"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { usePlatformUser } from "@/hooks/use-platform-user";
import { platformSession } from "@/lib/api";

export function PlatformShell({ children, title, adminOnly = false }: { children: React.ReactNode; title: string; adminOnly?: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const { user, error } = usePlatformUser();
  useEffect(() => { if (!platformSession.get()) router.replace("/platform/login"); else setReady(true); }, [router]);
  if (!ready || !user) return <main className="p-8 text-sm text-slate-500">{error || "Checking your session…"}</main>;
  const restricted = adminOnly || pathname === "/platform/tenants/new" || pathname.startsWith("/platform/users") || pathname.startsWith("/platform/administration");
  if (restricted && user.role !== "platform_admin") return <main className="mx-auto max-w-xl p-10"><h1 className="text-2xl font-semibold">Access forbidden</h1><p className="mt-2 text-sm text-slate-500">Platform administrator access is required for this page.</p></main>;
  const admin = user.role === "platform_admin";
  const items = admin
    ? [{ label: "Tenants", href: "/platform/tenants" }, { label: "Connectors", href: "/platform/connectors" }, { label: "Administration", href: "/platform/administration" }]
    : [{ label: "Overview", href: "/platform/overview" }, { label: "Tenants", href: "/platform/tenants" }, { label: "Connectors", href: "/platform/connectors" }];
  return <AppShell title={title} subtitle={admin ? "Administrator access" : "Executive overview"} userLabel={user.full_name} profileHref="/platform/profile" items={items} onLogout={() => { platformSession.clear(); router.replace("/platform/login"); }}>{children}</AppShell>;
}
