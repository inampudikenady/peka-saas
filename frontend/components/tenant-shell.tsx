"use client";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { tenantApi } from "@/lib/api";
import type { TenantMe } from "@/lib/types";

export function TenantShell({ slug, user, children, title, adminOnly = false }: { slug: string; user: TenantMe; children: React.ReactNode; title: string; adminOnly?: boolean }) {
  const router = useRouter(); const admin = user.role === "tenant_admin";
  if (adminOnly && !admin) return <main className="mx-auto max-w-xl p-10"><h1 className="text-2xl font-semibold">Access forbidden</h1><p className="mt-2 text-sm text-slate-500">Tenant administrator access is required.</p><Link className="mt-4 inline-block text-blue-600 hover:underline" href={`/t/${slug}/ai`}>Go to AI Assistant</Link></main>;
  const items = admin ? [
    { label: "AI Assistant", href: `/t/${slug}/ai` },
    { label: "Connectors", href: `/t/${slug}/connectors` },
    { label: "Administration", href: `/t/${slug}/administration` },
  ] : [{ label: "AI Assistant", href: `/t/${slug}/ai` }, { label: "Connectors", href: `/t/${slug}/connectors` }];
  return <AppShell title={title} subtitle={`${user.tenant_name} · ${admin ? "Tenant administrator" : "Tenant user"}`} userLabel={user.full_name} profileHref={`/t/${slug}/profile`} passwordManaged={user.auth_source==="sso"} items={items} onLogout={async () => { try { await tenantApi.logout(slug); } finally { router.replace(`/t/${slug}/login`); } }}>{children}</AppShell>;
}
