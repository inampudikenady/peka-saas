import { LoaderCircle } from "lucide-react";
import Link from "next/link";
import {
  ConnectorStatusBadge,
  LastHeartbeat,
} from "@/components/connector-presenters";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { ManagedConnector } from "@/lib/types";

type Props = {
  connectors: ManagedConnector[];
  detailBase: string;
  platform?: boolean;
  canRetire?: boolean;
  refreshingIds?: ReadonlySet<string>;
  onRefresh?: (connector: ManagedConnector) => void;
  onRetire?: (connector: ManagedConnector) => void;
};

function ConnectorActions({
  connector,
  canRetire,
  refreshing,
  onRefresh,
  onRetire,
}: {
  connector: ManagedConnector;
  canRetire: boolean;
  refreshing: boolean;
  onRefresh?: (connector: ManagedConnector) => void;
  onRetire?: (connector: ManagedConnector) => void;
}) {
  return (
    <div className="flex flex-nowrap items-center gap-2 max-sm:flex-wrap">
      {onRefresh && (
        <Button
          type="button"
          variant="outline"
          className="h-9 whitespace-nowrap px-3"
          disabled={refreshing}
          aria-label={`Refresh status for ${connector.name}`}
          aria-busy={refreshing}
          onClick={() => onRefresh(connector)}
        >
          {refreshing && (
            <LoaderCircle
              aria-hidden="true"
              className="mr-2 h-4 w-4 animate-spin"
              data-testid={`refresh-spinner-${connector.id}`}
            />
          )}
          Refresh
        </Button>
      )}
      {canRetire && !connector.retired_at && (
        <Button
          type="button"
          variant="danger"
          className="h-9 px-3"
          onClick={() => onRetire?.(connector)}
        >
          Retire
        </Button>
      )}
    </div>
  );
}

export function ConnectorTable({
  connectors,
  detailBase,
  platform = false,
  canRetire = false,
  refreshingIds = new Set<string>(),
  onRefresh,
  onRetire,
}: Props) {
  if (!connectors.length) {
    return (
      <Card className="p-8 text-center text-sm text-peka-secondary">
        No connectors have been registered.
      </Card>
    );
  }

  const headers = platform
    ? ["Connector", "Tenant", "Version", "Environment", "Status", "Last heartbeat", "Actions"]
    : ["Connector", "Version", "Environment", "Status", "Last heartbeat", "Actions"];

  return (
    <Card className="overflow-hidden" data-testid="connector-inventory-table">
      <table className="hidden w-full table-fixed text-left text-sm xl:table">
        <colgroup>
          {(platform
            ? ["22%", "15%", "10%", "11%", "13%", "17%", "12%"]
            : ["27%", "12%", "13%", "15%", "17%", "16%"]
          ).map((width, index) => <col key={index} style={{ width }} />)}
        </colgroup>
        <thead className="border-b border-peka-border bg-peka-app">
          <tr>
            {headers.map((value, index) => (
              <th
                className={`${index === 0 ? "pl-5" : "pl-3"} break-words py-3 pr-3 font-medium text-peka-secondary`}
                key={value}
              >
                {value}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {connectors.map((connector) => {
            const timeZone = connector.tenant_timezone ?? "UTC";
            const refreshing = refreshingIds.has(connector.id);
            return (
              <tr
                className="border-b border-peka-border align-top hover:bg-peka-primary-subtle last:border-0"
                key={connector.id}
              >
                <td className="break-words py-4 pl-5 pr-3 font-medium">
                  <Link
                    className="rounded-sm text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2"
                    href={`${detailBase}/${connector.id}`}
                  >
                    {connector.name}
                  </Link>
                </td>
                {platform && <td className="break-words py-4 pl-3 pr-3">{connector.tenant_name ?? "Unknown tenant"}</td>}
                <td className="break-words py-4 pl-3 pr-3">{connector.version}</td>
                <td className="break-words py-4 pl-3 pr-3">{connector.environment}</td>
                <td className="py-4 pl-3 pr-3"><ConnectorStatusBadge status={connector.status} /></td>
                <td className="break-words py-4 pl-3 pr-3">
                  <LastHeartbeat value={connector.last_heartbeat_at} timeZone={timeZone} />
                </td>
                <td className="py-4 pl-3 pr-4">
                  <ConnectorActions
                    connector={connector}
                    canRetire={canRetire}
                    refreshing={refreshing}
                    onRefresh={onRefresh}
                    onRetire={onRetire}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="divide-y divide-peka-border xl:hidden">
        {connectors.map((connector) => {
          const timeZone = connector.tenant_timezone ?? "UTC";
          const refreshing = refreshingIds.has(connector.id);
          return (
            <article className="space-y-4 p-5" key={connector.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    className="break-words rounded-sm font-medium text-peka-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-peka-focus-ring focus-visible:ring-offset-2"
                    href={`${detailBase}/${connector.id}`}
                  >
                    {connector.name}
                  </Link>
                  <p className="mt-1 break-words text-xs text-peka-secondary">
                    {connector.environment} • {connector.version}
                    {platform && connector.tenant_name ? ` • ${connector.tenant_name}` : ""}
                  </p>
                </div>
                <ConnectorStatusBadge status={connector.status} />
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-peka-secondary">Last heartbeat</dt>
                  <dd><LastHeartbeat value={connector.last_heartbeat_at} timeZone={timeZone} /></dd>
                </div>
              </dl>
              <ConnectorActions
                connector={connector}
                canRetire={canRetire}
                refreshing={refreshing}
                onRefresh={onRefresh}
                onRetire={onRetire}
              />
            </article>
          );
        })}
      </div>
    </Card>
  );
}
