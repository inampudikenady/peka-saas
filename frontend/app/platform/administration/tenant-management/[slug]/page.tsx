"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { InvitationActions } from "@/components/invitation-preview";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { canonicalTimezone, TimezoneSelector } from "@/components/timezone-selector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { platformApi } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import type {
  Tenant,
  TenantAdminInvite,
  TenantAdministrator,
  TenantAuditEvent,
  TenantPlatformSummary,
} from "@/lib/types";

export default function ManageTenantPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [invite, setInvite] = useState<TenantAdminInvite | null>(null);
  const [generated, setGenerated] = useState<TenantAdminInvite | null>(null);
  const [summary, setSummary] = useState<TenantPlatformSummary | null>(null);
  const [audit, setAudit] = useState<TenantAuditEvent[]>([]);
  const [administrators, setAdministrators] = useState<TenantAdministrator[]>([]);
  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [lifecycleDialogOpen, setLifecycleDialogOpen] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    const [item, status, overview, events, admins] = await Promise.all([
      platformApi.tenant(slug),
      platformApi.tenantInvite(slug),
      platformApi.tenantSummary(slug),
      platformApi.tenantAuditEvents(slug),
      typeof platformApi.tenantAdministrators === "function"
        ? platformApi.tenantAdministrators(slug)
        : Promise.resolve([]),
    ]);
    setTenant(item);
    setInvite(status);
    setSummary(overview);
    setAudit(events);
    setAdministrators(admins);
    setDisplayName(item.display_name);
    setTimezone(canonicalTimezone(item.timezone));
    setInviteEmail(status?.email ?? "");
    setInviteName(status?.full_name ?? "");
  }, [slug]);

  useEffect(() => {
    void load().catch((caught) => setError(caught.message));
  }, [load]);

  if (error && !tenant) {
    return <PlatformShell title="Tenant Management" adminOnly><Alert>{error}</Alert></PlatformShell>;
  }
  if (!tenant) {
    return <PlatformShell title="Tenant Management" adminOnly><p>Loading tenant…</p></PlatformShell>;
  }

  const tenantUrl = tenant.tenant_url ?? `/t/${tenant.slug}`;
  const mutate = async (operation: () => Promise<void>) => {
    setWorking(true);
    setError("");
    setSuccess("");
    try {
      await operation();
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Tenant update failed.");
    } finally {
      setWorking(false);
    }
  };

  const saveGeneral = () => mutate(async () => {
    const updated = await platformApi.updateTenant(slug, {
      display_name: displayName,
      timezone,
    });
    setTenant(updated);
    setSuccess("Tenant details saved.");
  });
  const updateRecipient = () => mutate(async () => {
    const next = await platformApi.updateInviteRecipient(slug, {
      email: inviteEmail,
      full_name: inviteName,
    });
    setGenerated(next);
    setSuccess("Initial administrator recipient updated. The previous link is invalid.");
  });
  const regenerate = () => mutate(async () => {
    const next = await platformApi.regenerateInvite(slug);
    setGenerated(next);
    setSuccess("A replacement one-time setup link was generated.");
  });
  const lifecycle = () => mutate(async () => {
    const updated = tenant.status === "active"
      ? await platformApi.deactivateTenant(slug)
      : await platformApi.activateTenant(slug);
    setTenant(updated);
    setLifecycleDialogOpen(false);
    setSuccess(`Tenant ${updated.status === "active" ? "reactivated" : "deactivated"}.`);
  });

  return (
    <PlatformShell title={`Manage ${tenant.display_name}`} adminOnly>
      <nav className="mb-4 text-sm text-slate-500" aria-label="Breadcrumb">
        <Link href="/platform/administration">Administration</Link> /{" "}
        <Link href="/platform/administration/tenant-management">Tenant Management</Link> /{" "}
        <span className="text-slate-900">{tenant.display_name}</span>
      </nav>
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      {success && <div className="mb-4"><Alert tone="success">{success}</Alert></div>}
      <div className="space-y-6">
        <Card>
          <CardHeader><h2 className="text-lg font-semibold">General tenant details</h2></CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium">Display name</span>
                <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium">Timezone</span>
                <TimezoneSelector value={timezone} onChange={(event) => setTimezone(event.target.value)} />
              </label>
            </div>
            <dl className="grid gap-5 sm:grid-cols-3">
              <Row label="Slug (read only)" value={tenant.slug} />
              <Row label="Status" value={<StatusBadge status={tenant.status} />} />
              <Row label="Tenant URL" value={tenantUrl} />
            </dl>
            <Button disabled={working || displayName.trim().length < 2} onClick={saveGeneral}>Save tenant details</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><h2 className="text-lg font-semibold">Operational summary</h2></CardHeader>
          <CardContent>
            <dl className="grid gap-5 sm:grid-cols-4">
              <Row label="SSO" value={summary?.sso_enabled ? "Enabled" : "Disabled"} />
              <Row label="Active users" value={summary?.active_user_count ?? 0} />
              <Row label="Administrators" value={summary?.administrator_count ?? 0} />
              <Row label="Connectors" value={summary?.connector_count ?? 0} />
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><h2 className="text-lg font-semibold">Administrator password recovery</h2><p className="text-sm text-slate-500">Tenant administrators and authentication type are listed below. Local administrators can receive a secure password-reset email. SSO credentials remain managed by the identity provider.</p></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-left text-sm"><thead className="border-b bg-slate-50"><tr><th className="p-3">Administrator</th><th className="p-3">Username</th><th className="p-3">Authentication</th><th className="p-3">Status</th><th className="p-3">Last login</th><th className="p-3">Action</th></tr></thead><tbody>{administrators.map((administrator) => <tr className="border-b" key={administrator.id}><td className="p-3"><strong>{administrator.full_name}</strong><div className="text-xs text-slate-500">{administrator.email}</div></td><td className="p-3">{administrator.username ?? "—"}</td><td className="p-3 uppercase">{administrator.auth_source}</td><td className="p-3">{administrator.is_active ? "Active" : "Inactive"}</td><td className="p-3">{administrator.last_login_at ? formatDateTime(administrator.last_login_at, tenant.timezone) : "Never"}</td><td className="p-3">{administrator.auth_source === "local" ? <Button variant="outline" disabled={working || !administrator.is_active} onClick={() => mutate(async () => { await platformApi.sendTenantAdministratorPasswordReset(slug, administrator.id); setSuccess("Password reset email captured. Open the Development Email Outbox to view it."); })}>Send password reset</Button> : <span className="text-xs text-slate-500">Managed by IdP</span>}</td></tr>)}</tbody></table>
            {administrators.length === 0 && <p className="p-4 text-sm text-slate-500">No tenant administrators found.</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><h2 className="text-lg font-semibold">{invite?.used_at ? "Tenant setup" : "Initial administrator invitation"}</h2></CardHeader>
          <CardContent className="space-y-4">
            {invite?.used_at ? (
              <dl className="grid gap-5 sm:grid-cols-3">
                <Row label="Status" value="Completed" />
                <Row label="Initial administrator" value={`${invite.full_name} · ${invite.email}`} />
                <Row label="Completed at" value={formatDateTime(invite.used_at, tenant.timezone)} />
              </dl>
            ) : (
              <>
                <dl className="grid gap-5 sm:grid-cols-3">
                  <Row label="Recipient" value={invite ? `${invite.full_name} · ${invite.email}` : "Not available"} />
                  <Row label="Status" value={invite ? <StatusBadge status={invite.status} /> : "Not available"} />
                  <Row label="Expires" value={invite ? formatDateTime(invite.expires_at, tenant.timezone) : "Not available"} />
                </dl>
                <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
                  <Input type="email" aria-label="Initial administrator email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} />
                  <Input aria-label="Initial administrator full name" value={inviteName} onChange={(event) => setInviteName(event.target.value)} />
                  <Button variant="outline" disabled={working} onClick={updateRecipient}>Update recipient</Button>
                </div>
                <Button variant="outline" disabled={working} onClick={regenerate}>Regenerate setup invitation</Button>
              </>
            )}
            {!invite?.used_at && generated?.setup_link && (
              <div className="rounded border border-amber-200 bg-amber-50 p-4">
                <p className="mb-2 text-sm">This newly generated link is shown once.</p>
                <code className="block overflow-x-auto bg-white p-2 text-xs">{generated.setup_link}</code>
                <div className="mt-3">
                  <InvitationActions email={generated.email} fullName={generated.full_name} displayName={tenant.display_name} tenantUrl={tenantUrl} setupLink={generated.setup_link} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><h2 className="text-lg font-semibold">Lifecycle</h2></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-500">{tenant.status === "active" ? "Deactivation blocks tenant routing and access. It is required before deletion." : "Activation restores tenant routing and access."}</p>
            {!lifecycleDialogOpen ? (
              <Button variant={tenant.status === "active" ? "outline" : "default"} disabled={working} onClick={() => setLifecycleDialogOpen(true)}>
                {tenant.status === "active" ? "Deactivate tenant" : "Reactivate tenant"}
              </Button>
            ) : (
              <div role="dialog" aria-modal="true" aria-labelledby="lifecycle-title" className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <h3 id="lifecycle-title" className="font-semibold">
                  {tenant.status === "active" ? "Deactivate tenant?" : "Reactivate tenant?"}
                </h3>
                <p className="mt-1 text-sm text-slate-600">
                  {tenant.status === "active"
                    ? "Tenant access and routing will be disabled until the tenant is reactivated."
                    : "Tenant access and routing will be restored."}
                </p>
                <div className="mt-3 flex gap-2">
                  <Button variant="outline" disabled={working} onClick={lifecycle}>{working ? "Updating…" : "Confirm"}</Button>
                  <Button variant="ghost" disabled={working} onClick={() => setLifecycleDialogOpen(false)}>Cancel</Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><h2 className="text-lg font-semibold">Audit history</h2></CardHeader>
          <CardContent className="space-y-3">
            {audit.length === 0 ? <p className="text-sm text-slate-500">No tenant management changes have been recorded yet.</p> : audit.map((event) => (
              <div className="rounded border p-3 text-sm" key={event.id}>
                <div className="flex flex-wrap justify-between gap-2"><strong>{event.action.replaceAll("_", " ")}</strong><time>{formatDateTime(event.created_at, tenant.timezone)}</time></div>
                <p className="mt-1 text-slate-500">By {event.actor_username}{event.request_id ? ` · Request ${event.request_id}` : ""}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="border-red-200">
          <CardHeader><h2 className="text-lg font-semibold text-red-900">Danger zone</h2></CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-red-800">
              Permanent deletion removes the tenant, users, SSO configuration, connectors, documents, and indexed knowledge. This cannot be undone.
            </p>
            {tenant.status === "active" ? (
              <div className="space-y-3">
                <p className="text-sm font-medium text-red-900">Deactivate the tenant before permanent deletion.</p>
                <Button variant="danger" disabled>Delete tenant</Button>
              </div>
            ) : (
              <ConfirmDialog tenantSlug={slug} onConfirm={async () => {
                await platformApi.deleteTenant(slug);
                router.replace("/platform/administration/tenant-management");
              }} />
            )}
          </CardContent>
        </Card>
      </div>
    </PlatformShell>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><dt className="text-xs font-medium uppercase text-slate-500">{label}</dt><dd className="mt-1 text-sm">{value || "Not configured"}</dd></div>;
}
