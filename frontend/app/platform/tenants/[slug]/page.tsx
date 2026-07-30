"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { usePlatformUser } from "@/hooks/use-platform-user";
import { platformApi } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import type { Tenant, TenantAdminInvite, TenantPlatformSummary } from "@/lib/types";

export default function TenantDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const { user } = usePlatformUser();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [invite, setInvite] = useState<TenantAdminInvite | null>(null);
  const [summary, setSummary] = useState<TenantPlatformSummary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      platformApi.tenant(slug),
      platformApi.tenantInvite(slug),
      platformApi.tenantSummary(slug),
    ]).then(([item, status, overview]) => {
      setTenant(item);
      setInvite(status);
      setSummary(overview);
    }).catch((caught) => setError(caught.message));
  }, [slug]);
  if (error) return <PlatformShell title="Tenant details"><Alert>{error}</Alert></PlatformShell>;
  if (!tenant) return <PlatformShell title="Tenant details"><p>Loading tenant…</p></PlatformShell>;
  const url = tenant.tenant_url ?? `/t/${tenant.slug}`;
  return (
    <PlatformShell title={tenant.display_name}>
      <nav className="mb-4 text-sm text-slate-500" aria-label="Breadcrumb">
        <Link href="/platform/tenants" className="hover:text-blue-600">Tenants</Link> /{" "}
        <span className="text-slate-900">{tenant.display_name}</span>
      </nav>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-semibold">{tenant.display_name}</h2>
        <StatusBadge status={tenant.status} />
        {user?.role === "platform_admin" && (
          <Button asChild variant="outline">
            <Link href={`/platform/administration/tenant-management/${tenant.slug}`}>Manage tenant</Link>
          </Button>
        )}
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader><h3 className="text-lg font-semibold">Tenant information</h3></CardHeader>
          <CardContent>
            <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Detail label="Display name" value={tenant.display_name} />
              <Detail label="Slug" value={tenant.slug} />
              <Detail label="Platform hostname" value={tenant.subdomain} />
              <Detail label="Timezone" value={tenant.timezone} />
              <Detail label="Created" value={formatDateTime(tenant.created_at, tenant.timezone)} />
              <Detail label="Updated" value={formatDateTime(tenant.updated_at, tenant.timezone)} />
              <div className="sm:col-span-2">
                <Detail label="Tenant URL" value={<div className="flex flex-wrap items-center gap-2"><span className="break-all">{url}</span><CopyButton value={url} /><Button asChild variant="outline"><a href={url} target="_blank" rel="noreferrer">Open portal</a></Button></div>} />
              </div>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><h3 className="text-lg font-semibold">Safe operational summary</h3></CardHeader>
          <CardContent>
            <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <Detail label="Initial administrator" value={invite ? `${invite.full_name} · ${invite.email}` : "Not available"} />
              <Detail label="Invitation status" value={invite ? <StatusBadge status={invite.status} /> : "Not available"} />
              <Detail label="Invitation expiry" value={invite ? formatDateTime(invite.expires_at, tenant.timezone) : "Not available"} />
              <Detail label="SSO" value={<StatusBadge status={summary?.sso_enabled ? "Enabled" : "Disabled"} />} />
              <Detail label="Local administrator" value={summary?.local_admin_active ? "Active" : "Not active"} />
              <Detail label="Active users" value={summary?.active_user_count ?? "Not available"} />
              <Detail label="Administrators" value={summary?.administrator_count ?? "Not available"} />
              <Detail label="Connectors" value={summary?.connector_count ?? "Not available"} />
            </dl>
          </CardContent>
        </Card>
      </div>
    </PlatformShell>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 text-sm">{value || "Not configured"}</dd></div>;
}
