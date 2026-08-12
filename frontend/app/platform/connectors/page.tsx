"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConnectorInventory } from "@/components/connector-inventory";
import { PlatformShell } from "@/components/platform-shell";
import { platformApi } from "@/lib/api";
import type { ManagedConnector } from "@/lib/types";

export default function Page() {
  const [items, setItems] = useState<ManagedConnector[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void platformApi.connectors(true).then(setItems).catch((reason) => setError(reason.message));
  }, []);

  const refresh = async (connector: ManagedConnector) => {
    const next = await platformApi.connector(connector.id);
    setItems((current) => current?.map((item) => item.id === next.id ? next : item) ?? []);
    return next;
  };

  return (
    <PlatformShell title="Connectors">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Platform Connectors</h1>
        <p className="text-sm text-peka-secondary">Connector inventory across all tenants.</p>
        <p className="mt-1 text-xs text-peka-secondary">
          Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.
        </p>
      </div>
      {error && <Alert>{error}</Alert>}
      {items ? (
        <ConnectorInventory
          connectors={items}
          detailBase="/platform/connectors"
          platform
          onRefresh={refresh}
        />
      ) : (
        <p className="text-sm text-peka-secondary">Loading connectors…</p>
      )}
    </PlatformShell>
  );
}
