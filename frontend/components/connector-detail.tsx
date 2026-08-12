import { ConnectorStatusBadge, LastHeartbeat } from "@/components/connector-presenters";
import { CopyButton } from "@/components/copy-button";
import { Card } from "@/components/ui/card";
import { formatDateTime } from "@/lib/datetime";
import type { ConnectorDetail as Detail } from "@/lib/types";

const label = (value: string) => value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ");
const capabilityLabels: Record<string, string> = {
  filesystem_documents: "Local document management",
  operational_tools: "Operational tools",
  local_knowledge: "Local Knowledge Store",
};

function DetailValue({ label, value, copy = false }: { label: string; value: string; copy?: boolean }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-peka-secondary">{label}</dt>
      <dd className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-sm">
        <span className={copy ? "min-w-0 break-all font-mono" : "break-words"}>{value}</span>
        {copy && <CopyButton value={value} label={`Copy ${label}`} />}
      </dd>
    </div>
  );
}

export function ConnectorDetail({ connector }: { connector: Detail }) {
  const timeZone = connector.tenant_timezone ?? "UTC";
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-semibold">General</h2>
          <dl className="mt-4 grid gap-4">
            <DetailValue label="Connector Name" value={connector.name} />
            <DetailValue label="Tenant" value={connector.tenant_name ?? connector.tenant_id} />
            <DetailValue label="Version" value={connector.version} />
            <DetailValue label="Environment" value={connector.environment} />
            <DetailValue label="Registered At" value={formatDateTime(connector.registered_at, timeZone)} />
            <DetailValue label="Instance ID" value={connector.instance_id} copy />
            <DetailValue label="Connector ID" value={connector.id} copy />
          </dl>
        </Card>
        <Card className="p-5">
          <h2 className="font-semibold">Status</h2>
          <div className="mt-4"><ConnectorStatusBadge status={connector.status} /></div>
          <p className="mt-3 text-xs text-peka-secondary">
            Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.
          </p>
          <dl className="mt-4 grid gap-3 text-sm">
            <div>
              <dt className="text-peka-secondary">Last heartbeat</dt>
              <dd>
                <LastHeartbeat value={connector.last_heartbeat_at} timeZone={timeZone} />
                {connector.last_heartbeat_at && <span className="ml-2 text-xs text-peka-secondary">{formatDateTime(connector.last_heartbeat_at, timeZone)}</span>}
              </dd>
            </div>
            <div><dt className="text-peka-secondary">Expected interval</dt><dd>{connector.heartbeat_interval_seconds} seconds</dd></div>
            <div><dt className="text-peka-secondary">Last seen</dt><dd>{connector.last_seen_at ? formatDateTime(connector.last_seen_at, timeZone) : "Never"}</dd></div>
          </dl>
        </Card>
      </div>
      <Card className="p-5">
        <h2 className="font-semibold">Integration health</h2>
        <p className="mt-2 text-sm text-peka-secondary">
          Individual integration health is not reported in the current connector heartbeat. PEKA does not infer provider health from aggregate source counts.
        </p>
        <div className="mt-4 rounded-md border border-peka-border bg-peka-app p-4 text-sm">
          Integration-specific status is not available for this connector.
        </div>
      </Card>
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Local Knowledge Store</h2>
            <p className="mt-1 text-sm text-peka-secondary">Summary reported by this Connector; customer content remains local.</p>
          </div>
          <span className="rounded-full bg-peka-info-subtle px-2.5 py-1 text-xs font-medium text-peka-info">
            {connector.local_knowledge_store_status ? label(connector.local_knowledge_store_status) : "Not reported"}
          </span>
        </div>
        <dl className="mt-4 grid gap-4 sm:grid-cols-3">
          <DetailValue label="Documents" value={(connector.knowledge_document_count ?? 0).toLocaleString()} />
          <DetailValue label="Indexed chunks" value={(connector.knowledge_indexed_chunk_count ?? 0).toLocaleString()} />
          <DetailValue label="Last indexing activity" value={connector.last_knowledge_index_activity_at ? formatDateTime(connector.last_knowledge_index_activity_at, timeZone) : "Not reported"} />
        </dl>
      </Card>
      <Card className="p-5">
        <h2 className="font-semibold">Reported capabilities</h2>
        <p className="mt-1 text-sm text-peka-secondary">Capabilities confirm supported operations; they are not health indicators.</p>
        {connector.capabilities.length ? (
          <ul className="mt-4 divide-y divide-peka-border rounded-md border border-peka-border">
            {connector.capabilities.map((item) => (
              <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm" key={item}>
                <span>{capabilityLabels[item] ?? label(item)}</span>
                <span className="rounded-full bg-peka-info-subtle px-2.5 py-1 text-xs font-medium text-peka-info">Reported</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-3 text-sm text-peka-secondary">No capabilities reported.</p>}
      </Card>
      <Card className="overflow-x-auto">
        <div className="border-b border-peka-border p-5">
          <h2 className="font-semibold">Recent heartbeats</h2>
          <p className="text-sm text-peka-secondary">Detailed history is retained for 30 days.</p>
        </div>
        <table className="w-full text-left text-sm">
          <thead><tr>{["Received", "Version", "Uptime", "Reported status", "Result"].map((value) => <th className="px-4 py-3 text-peka-secondary" key={value}>{value}</th>)}</tr></thead>
          <tbody>{connector.recent_heartbeats.map((item, index) => <tr className="border-t border-peka-border" key={`${item.received_at}-${index}`}><td className="px-4 py-3">{formatDateTime(item.received_at, timeZone)}</td><td className="px-4">{item.version}</td><td className="px-4">{item.uptime_seconds}s</td><td className="px-4">{label(item.reported_status)}</td><td className="px-4">{item.accepted ? "Accepted" : "Rejected"}</td></tr>)}</tbody>
        </table>
        {!connector.recent_heartbeats.length && <p className="p-5 text-sm text-peka-secondary">No heartbeats received.</p>}
      </Card>
      <Card>
        <div className="border-b border-peka-border p-5"><h2 className="font-semibold">Recent events</h2></div>
        <div className="divide-y divide-peka-border">
          {connector.recent_events.map((event, index) => <div className="p-4 text-sm" key={`${event.occurred_at}-${index}`}><div className="flex flex-wrap justify-between gap-4"><strong>{label(event.event_type)}</strong><time className="text-xs text-peka-secondary">{formatDateTime(event.occurred_at, timeZone)}</time></div>{event.detail && <p className="mt-1 text-peka-secondary">{event.detail}</p>}</div>)}
          {!connector.recent_events.length && <p className="p-5 text-sm text-peka-secondary">No events recorded.</p>}
        </div>
      </Card>
    </div>
  );
}
