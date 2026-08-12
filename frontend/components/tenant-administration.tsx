"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { TenantShell } from "@/components/tenant-shell";
import { useTenantUser } from "@/hooks/use-tenant-user";
export const tenantAdministrationTabs = [["Users", "users"], ["Authentication", "authentication"], ["Tenant settings", "settings"], ["Audit", "audit"]];
export function TenantAdministration({ title, children }: { title: string; children: React.ReactNode }) { const { tenantSlug } = useParams<{ tenantSlug: string }>(); const { user, error } = useTenantUser(tenantSlug); if (error) return <main className="p-8">{error}</main>; if (!user) return <main className="p-8 text-sm text-slate-500">Loading administration…</main>; return <TenantShell slug={tenantSlug} user={user} title={title} adminOnly><nav aria-label="Administration sections" className="mb-6 flex gap-1 overflow-x-auto border-b">{tenantAdministrationTabs.map(([label, path]) => <Link key={path} className="whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm text-slate-600 hover:border-blue-600 hover:text-blue-700" href={`/t/${tenantSlug}/administration/${path}`}>{label}</Link>)}</nav>{children}</TenantShell>; }
