"use client";

import { useState } from "react";
import { ConnectorTable } from "@/components/connector-table";
import type { ManagedConnector } from "@/lib/types";

export function ConnectorInventory({
  connectors,
  detailBase,
  platform = false,
  canRetire = false,
  onRetire,
}: {
  connectors: ManagedConnector[];
  detailBase: string;
  platform?: boolean;
  canRetire?: boolean;
  onRetire?: (connector: ManagedConnector) => void;
}) {
  const [showRetired, setShowRetired] = useState(false);
  const visible = showRetired
    ? connectors
    : connectors.filter((connector) => connector.retired_at === null);
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={showRetired}
          onChange={(event) => setShowRetired(event.target.checked)}
        />
        Show retired connectors
      </label>
      <ConnectorTable
        connectors={visible}
        detailBase={detailBase}
        platform={platform}
        canRetire={canRetire}
        onRetire={onRetire}
      />
    </div>
  );
}
