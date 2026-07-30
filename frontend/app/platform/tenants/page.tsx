"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { platformApi } from "@/lib/api";
import { formatDate } from "@/lib/datetime";
import type { Tenant, TenantAdminInvite } from "@/lib/types";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [invites, setInvites] = useState<Record<string, TenantAdminInvite | null>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    platformApi.tenants().then(async (items) => {
      setTenants(items);
      const statuses = await Promise.all(items.map(async (tenant) => [
        tenant.slug,
        await platformApi.tenantInvite(tenant.slug),
      ] as const));
      setInvites(Object.fromEntries(statuses));
    }).catch((caught) => setError(caught.message));
  }, []);
  return (
    <PlatformShell title="Tenants">
      <nav className="mb-4 text-sm text-slate-500" aria-label="Breadcrumb">Platform / <span className="text-slate-900">Tenants</span></nav>
      <div className="mb-6"><h2 className="text-2xl font-semibold">Tenants</h2><p className="text-sm text-slate-500">Tenant directory and operational access.</p></div>
      {error && <Alert>{error}</Alert>}
      {!tenants && <p className="text-sm text-slate-500">Loading tenants…</p>}
      {tenants && <Card className="overflow-x-auto">
        <table className="w-full min-w-max text-left text-sm">
          <thead className="border-b bg-slate-50"><tr>{["Tenant", "URL", "Status", "Timezone", "Created", "Setup", "Actions"].map((label) => <th key={label} className="whitespace-nowrap px-4 py-3 font-medium text-slate-500">{label}</th>)}</tr></thead>
          <tbody>{tenants.map((tenant) => {
            const url = tenant.tenant_url ?? `/t/${tenant.slug}`;
            return <tr key={tenant.id} className="border-b align-top last:border-0">
              <td className="px-4 py-4"><Link href={`/platform/tenants/${tenant.slug}`} className="font-medium text-blue-600">{tenant.display_name}</Link><div className="font-mono text-xs text-slate-500">{tenant.slug}</div></td>
              <td className="max-w-xs px-4 py-4 text-xs">{url}</td>
              <td className="px-4 py-4"><StatusBadge status={tenant.status} /></td>
              <td className="px-4 py-4">{tenant.timezone}</td>
              <td className="whitespace-nowrap px-4 py-4">{formatDate(tenant.created_at, tenant.timezone)}</td>
              <td className="px-4 py-4">{invites[tenant.slug] ? <StatusBadge status={invites[tenant.slug]!.status} /> : "Not available"}</td>
              <td className="min-w-80 px-4 py-4"><div className="flex flex-nowrap gap-2"><Button asChild variant="outline"><a href={url} target="_blank" rel="noreferrer">Open portal</a></Button><Button asChild variant="outline"><Link href={`/platform/tenants/${tenant.slug}`}>Details</Link></Button><CopyButton value={url} /></div></td>
            </tr>;
          })}</tbody>
        </table>
      </Card>}
    </PlatformShell>
  );
}
