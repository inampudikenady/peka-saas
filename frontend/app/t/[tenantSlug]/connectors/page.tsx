"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConnectorInventory } from "@/components/connector-inventory";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { ManagedConnector } from "@/lib/types";

export default function ConnectorsPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const { user, error: userError } = useTenantUser(tenantSlug);
  const [items, setItems] = useState<ManagedConnector[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (user?.role !== "tenant_admin") return;
    void tenantApi.connectors(tenantSlug, true).then(setItems).catch((reason) => setError(reason.message));
  }, [tenantSlug, user?.role]);

  if (!user) return <main className="p-8">{userError || "Loading…"}</main>;

  const refresh = async (connector: ManagedConnector) => {
    const next = await tenantApi.connector(tenantSlug, connector.id);
    setItems((current) => current?.map((item) => item.id === next.id ? next : item) ?? []);
    return next;
  };

  const retire = async (connector: ManagedConnector) => {
    if (!window.confirm(`Retire ${connector.name}? It will no longer be able to authenticate.`)) return;
    try {
      const next = await tenantApi.retireConnector(tenantSlug, connector.id);
      setItems((current) => current?.map((item) => item.id === next.id ? next : item) ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retirement failed.");
    }
  };

  return (
    <TenantShell slug={tenantSlug} user={user} title="Connectors" adminOnly>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold">Connectors</h2>
          <p className="text-sm text-peka-secondary">Customer appliance communication and local source health.</p>
          <p className="mt-1 text-xs text-peka-secondary">
            Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.
          </p>
        </div>
        <Button asChild><Link href={`/t/${tenantSlug}/connectors/registration-tokens`}>Registration tokens</Link></Button>
      </div>
      {error && <Alert>{error}</Alert>}
      {items ? (
        <ConnectorInventory
          connectors={items}
          detailBase={`/t/${tenantSlug}/connectors`}
          canRetire={user.role === "tenant_admin"}
          onRefresh={refresh}
          onRetire={retire}
        />
      ) : (
        <p className="text-sm text-peka-secondary">Loading connectors…</p>
      )}
    </TenantShell>
  );
}
