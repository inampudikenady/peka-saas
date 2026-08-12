"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { platformApi } from "@/lib/api";
import { formatDate } from "@/lib/datetime";
import type { Tenant } from "@/lib/types";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    platformApi.tenants().then(setTenants).catch((caught) => setError(caught.message));
  }, []);
  return (
    <PlatformShell title="Tenants">
      <nav className="mb-4 text-sm text-slate-500" aria-label="Breadcrumb">Platform / <span className="text-slate-900">Tenants</span></nav>
      <div className="mb-6"><h2 className="text-2xl font-semibold">Tenants</h2><p className="text-sm text-slate-500">Tenant directory and operational access.</p></div>
      {error && <Alert>{error}</Alert>}
      {!tenants && <p className="text-sm text-slate-500">Loading tenants…</p>}
      {tenants && <Card className="overflow-hidden" data-testid="tenant-inventory">
        <table className="hidden w-full table-fixed text-left text-sm lg:table">
          <colgroup><col className="w-[26%]"/><col className="w-[44%]"/><col className="w-[14%]"/><col className="w-[16%]"/></colgroup>
          <thead className="border-b border-peka-border bg-peka-app"><tr>{["Tenant", "URL", "Status", "Created"].map((label) => <th key={label} className="px-4 py-3 font-medium text-peka-secondary">{label}</th>)}</tr></thead>
          <tbody>{tenants.map((tenant) => {
            const url = tenant.tenant_url ?? `/t/${tenant.slug}`;
            return <tr key={tenant.id} className="border-b border-peka-border align-top last:border-0">
              <td className="px-4 py-4"><Link href={`/platform/tenants/${tenant.slug}`} className="rounded-sm font-medium text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2">{tenant.display_name}</Link><div className="font-mono text-xs text-peka-secondary">{tenant.slug}</div></td>
              <td className="min-w-0 px-4 py-4"><div className="flex min-w-0 items-center gap-1"><a href={url} target="_blank" rel="noopener noreferrer" title={url} aria-label={`Open ${tenant.display_name} portal: ${url}`} className="min-w-0 truncate rounded-sm text-xs text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2">{url}</a><CopyButton value={url} label="Copy tenant URL" iconOnly/></div></td>
              <td className="px-4 py-4"><StatusBadge status={tenant.status} /></td>
              <td className="whitespace-nowrap px-4 py-4">{formatDate(tenant.created_at, tenant.timezone)}</td>
            </tr>;
          })}</tbody>
        </table>
        <div className="divide-y divide-peka-border lg:hidden">{tenants.map((tenant) => {
          const url = tenant.tenant_url ?? `/t/${tenant.slug}`;
          return <article className="space-y-3 p-4" key={tenant.id}>
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><Link href={`/platform/tenants/${tenant.slug}`} className="rounded-sm font-medium text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2">{tenant.display_name}</Link><div className="font-mono text-xs text-peka-secondary">{tenant.slug}</div></div><StatusBadge status={tenant.status}/></div>
            <div className="flex min-w-0 items-center gap-1"><a href={url} target="_blank" rel="noopener noreferrer" title={url} aria-label={`Open ${tenant.display_name} portal: ${url}`} className="min-w-0 truncate rounded-sm text-xs text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2">{url}</a><CopyButton value={url} label="Copy tenant URL" iconOnly/></div>
            <p className="text-xs text-peka-secondary">Created {formatDate(tenant.created_at, tenant.timezone)}</p>
          </article>;
        })}</div>
      </Card>}
    </PlatformShell>
  );
}
