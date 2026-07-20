"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Alert } from "@/components/alert";
import { MetricCard } from "@/components/metric-card";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePlatformUser } from "@/hooks/use-platform-user";
import { platformApi } from "@/lib/api";
import type { Tenant } from "@/lib/types";

export default function PlatformOverview() {
  const router = useRouter();
  const { user, error: identityError } = usePlatformUser();
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (user?.role === "platform_admin") router.replace("/platform/tenants");
    if (user?.role === "platform_readonly") {
      Promise.all([platformApi.tenants(), platformApi.health()])
        .then(([items, health]) => { setTenants(items); setHealthy(health.status === "ok"); })
        .catch(caught => setError(caught instanceof Error ? caught.message : "Overview data could not be loaded."));
    }
  }, [router, user]);

  const recent = useMemo(() => [...(tenants ?? [])].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 5), [tenants]);
  if (!user || user.role !== "platform_readonly") return <main className="p-8 text-sm text-slate-500">{identityError || "Loading overview…"}</main>;

  return <PlatformShell title="Overview">
    <div className="mb-8"><h2 className="text-2xl font-semibold">Platform overview</h2><p className="mt-1 text-sm text-slate-500">Live adoption visibility and quick access to tenant portals.</p></div>
    {error && <Alert>{error}</Alert>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard label="Total tenants" value={tenants?.length ?? "Loading…"}/>
      <MetricCard label="Active tenants" value={tenants?.filter(tenant => tenant.status === "active").length ?? "Loading…"}/>
      <MetricCard label="Suspended tenants" value={tenants?.filter(tenant => tenant.status === "suspended").length ?? "Loading…"}/>
      <MetricCard label="Platform health" value={healthy === null ? "Checking…" : healthy ? "Operational" : "Unavailable"} detail="Reported by FastAPI /health"/>
    </div>
    <Card className="mt-8 overflow-hidden">
      <div className="border-b px-5 py-4"><h3 className="font-semibold">Recent tenants</h3><p className="text-sm text-slate-500">Open a tenant portal for demonstrations or observation.</p></div>
      {recent.length === 0 && tenants ? <p className="p-5 text-sm text-slate-500">No tenants are available.</p> : <div className="divide-y">{recent.map(tenant => <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between" key={tenant.id}><div><p className="font-medium">{tenant.display_name}</p><p className="text-xs text-slate-500">{tenant.slug}</p></div><div className="flex items-center gap-3"><StatusBadge status={tenant.status}/>{tenant.tenant_url ? <Button variant="outline" asChild><Link href={tenant.tenant_url}>Open portal</Link></Button> : <span className="text-xs text-slate-500">URL unavailable</span>}</div></div>)}</div>}
    </Card>
    <Card className="mt-6 p-5"><h3 className="font-semibold">Coming soon</h3><p className="mt-1 text-sm text-slate-500">User adoption, connector usage, AI usage, and licensing summaries require real aggregate APIs and are deferred.</p></Card>
  </PlatformShell>;
}
