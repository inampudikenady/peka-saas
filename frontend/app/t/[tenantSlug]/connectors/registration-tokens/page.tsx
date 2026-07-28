"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { RegistrationTokenTable } from "@/components/registration-token-table";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { RegistrationToken, RegistrationTokenCreated } from "@/lib/types";

export default function Page() {
  const { tenantSlug } = useParams<{tenantSlug: string}>();
  const { user } = useTenantUser(tenantSlug);
  const [items, setItems] = useState<RegistrationToken[]>([]);
  const [created, setCreated] = useState<RegistrationTokenCreated | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => tenantApi.registrationTokens(tenantSlug, true).then(setItems).catch((nextError) => setError(nextError.message)), [tenantSlug]);
  useEffect(() => {
    if (user?.role === "tenant_admin") void load();
  }, [load, user?.role]);
  if (!user) return <main className="p-8">Loading…</main>;

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const token = await tenantApi.createRegistrationToken(tenantSlug);
      setCreated(token);
      setItems((current) => [token, ...current]);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Could not generate token.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (token: RegistrationToken) => {
    if (!window.confirm("Revoke this unused token?")) return;
    try {
      await tenantApi.revokeRegistrationToken(tenantSlug, token.id);
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Revocation failed.");
    }
  };

  return (
    <TenantShell slug={tenantSlug} user={user} title="Registration tokens" adminOnly>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Registration Tokens</h1>
          <p className="text-sm text-slate-500">Generate a single-use registration token for this tenant. The connector reports its own display name during registration.</p>
        </div>
        <Button asChild variant="outline"><Link href={`/t/${tenantSlug}/connectors`}>Back to connectors</Link></Button>
      </div>
      {error && <Alert>{error}</Alert>}
      {created && (
        <div className="mb-6 rounded-lg border border-amber-300 bg-amber-50 p-5">
          <h2 className="font-semibold">Copy this token now</h2>
          <p className="mt-1 text-sm text-amber-900">This is the only time PEKA will display the raw registration token.</p>
          <code className="my-4 block overflow-x-auto rounded bg-white p-3 text-xs">{created.registration_token}</code>
          <CopyButton value={created.registration_token}/>
          <Button className="ml-2" variant="ghost" onClick={() => setCreated(null)}>Dismiss</Button>
        </div>
      )}
      {user.role === "tenant_admin" && (
        <Card className="mb-6 p-5">
          <h2 className="font-semibold">Generate token</h2>
          <p className="mt-1 text-sm text-slate-500">Single-use credentials expire after 30 minutes and are stored as hashes.</p>
          <Button className="mt-3" disabled={busy} onClick={generate}>{busy ? "Generating…" : "Generate token"}</Button>
        </Card>
      )}
      <RegistrationTokenTable items={items} canRevoke={user.role === "tenant_admin"} onRevoke={revoke}/>
    </TenantShell>
  );
}
