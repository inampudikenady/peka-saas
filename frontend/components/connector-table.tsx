import Link from "next/link";
import {
  ConnectorStatusBadge,
  LastHeartbeat,
  SourceSummary,
} from "@/components/connector-presenters";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDateTime } from "@/lib/datetime";
import type { ManagedConnector } from "@/lib/types";

type Props = {
  connectors: ManagedConnector[];
  detailBase: string;
  platform?: boolean;
  canRetire?: boolean;
  onRetire?: (connector: ManagedConnector) => void;
};

export function ConnectorTable({
  connectors,
  detailBase,
  platform = false,
  canRetire = false,
  onRetire,
}: Props) {
  if (!connectors.length) {
    return (
      <Card className="p-8 text-center text-sm text-slate-500">
        No connectors have been registered.
      </Card>
    );
  }
  const headers = platform
    ? ["Connector Name", "Tenant", "Version", "Environment", "Instance ID", "Connector ID", "Status", "Last Heartbeat", "Sources", "Actions"]
    : ["Name", "Version", "Environment", "Status", "Last heartbeat", "Source summary", "Registered at", "Actions"];
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-max text-left text-sm">
        <thead className="border-b bg-slate-50">
          <tr>
            {headers.map((value, index) => (
              <th
                className={`whitespace-nowrap py-3 font-medium text-slate-500 ${
                  index === 0
                    ? "pl-6 pr-4"
                    : value === "Actions"
                      ? `${platform ? "w-72 min-w-72" : "w-48 min-w-48"} px-4 pr-6`
                      : "px-4"
                }`}
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
            return (
              <tr className="border-b align-top last:border-0" key={connector.id}>
                <td className="py-4 pl-6 pr-4 font-medium">
                  <Link className="text-blue-600 hover:underline" href={`${detailBase}/${connector.id}`}>
                    {connector.name}
                  </Link>
                </td>
                {platform && <td className="px-4 py-4">{connector.tenant_name ?? "Unknown tenant"}</td>}
                <td className="px-4 py-4">{connector.version}</td>
                <td className="px-4 py-4">{connector.environment}</td>
                {platform && (
                  <>
                    <td className="px-4 py-4 font-mono text-xs">{connector.instance_id}</td>
                    <td className="px-4 py-4 font-mono text-xs">{connector.id}</td>
                  </>
                )}
                <td className="px-4 py-4"><ConnectorStatusBadge status={connector.status} /></td>
                <td className="whitespace-nowrap px-4 py-4">
                  <LastHeartbeat value={connector.last_heartbeat_at} timeZone={timeZone} />
                </td>
                <td className="whitespace-nowrap px-4 py-4">
                  <SourceSummary
                    total={connector.source_total}
                    healthy={connector.source_healthy}
                    unhealthy={connector.source_unhealthy}
                    disabled={connector.source_disabled}
                  />
                </td>
                {!platform && (
                  <td className="whitespace-nowrap px-4 py-4">
                    {formatDateTime(connector.registered_at, timeZone)}
                  </td>
                )}
                <td className={`${platform ? "w-72 min-w-72" : "w-48 min-w-48"} px-4 py-4 pr-6`}>
                  <div className="flex flex-nowrap items-center gap-2 whitespace-nowrap">
                    <Button asChild variant="outline" className="shrink-0 whitespace-nowrap">
                      <Link href={`${detailBase}/${connector.id}`}>Details</Link>
                    </Button>
                    {platform && connector.tenant_slug && (
                      <Button asChild variant="ghost" className="shrink-0 whitespace-nowrap">
                        <a href={`/t/${connector.tenant_slug}`} target="_blank" rel="noreferrer">
                          Open tenant portal
                        </a>
                      </Button>
                    )}
                    {canRetire && !connector.retired_at && (
                      <Button
                        variant="danger"
                        className="shrink-0 whitespace-nowrap"
                        onClick={() => onRetire?.(connector)}
                      >
                        Retire
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
