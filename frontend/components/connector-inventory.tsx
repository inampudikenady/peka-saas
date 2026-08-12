"use client";

import { useState } from "react";
import { ConnectorTable } from "@/components/connector-table";
import type { ManagedConnector } from "@/lib/types";

type Notice = { tone: "success" | "error"; message: string } | null;

export function ConnectorInventory({
  connectors,
  detailBase,
  platform = false,
  canRetire = false,
  onRefresh,
  onRetire,
}: {
  connectors: ManagedConnector[];
  detailBase: string;
  platform?: boolean;
  canRetire?: boolean;
  onRefresh?: (connector: ManagedConnector) => Promise<ManagedConnector>;
  onRetire?: (connector: ManagedConnector) => void;
}) {
  const [showRetired, setShowRetired] = useState(false);
  const [refreshingIds, setRefreshingIds] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<Notice>(null);
  const visible = showRetired
    ? connectors
    : connectors.filter((connector) => connector.retired_at === null);

  const refresh = async (connector: ManagedConnector) => {
    if (!onRefresh || refreshingIds.has(connector.id)) return;
    setRefreshingIds((current) => new Set(current).add(connector.id));
    setNotice(null);
    try {
      await onRefresh(connector);
      setNotice({ tone: "success", message: `${connector.name} status refreshed.` });
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "Connector status could not be refreshed.",
      });
    } finally {
      setRefreshingIds((current) => {
        const next = new Set(current);
        next.delete(connector.id);
        return next;
      });
    }
  };

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-peka-secondary">
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
        refreshingIds={refreshingIds}
        onRefresh={onRefresh ? refresh : undefined}
        onRetire={onRetire}
      />
      {notice && (
        <div
          className={`fixed bottom-6 right-6 z-50 max-w-sm rounded-md border px-4 py-3 text-sm shadow-card ${
            notice.tone === "success"
              ? "border-peka-success bg-peka-success-subtle text-peka-success"
              : "border-peka-danger bg-peka-danger-subtle text-peka-danger"
          }`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.message}
        </div>
      )}
    </div>
  );
}
