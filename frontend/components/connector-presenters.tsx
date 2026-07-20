import { StatusBadge } from "@/components/status-badge";

export function LastHeartbeat({ value }: { value: string | null }) {
  if (!value) return <span className="text-slate-500">Never</span>;
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000));
  const relative = seconds < 60 ? `${seconds} seconds ago` : seconds < 3600 ? `${Math.floor(seconds / 60)} minutes ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)} hours ago` : `${Math.floor(seconds / 86400)} days ago`;
  return <time dateTime={value} title={new Date(value).toISOString()}>{relative}</time>;
}

export function SourceSummary({ total, healthy, unhealthy, disabled }: { total: number; healthy: number; unhealthy: number; disabled: number }) {
  return <span title={`${healthy} healthy, ${unhealthy} unhealthy, ${disabled} disabled`}>{healthy}/{total} healthy{unhealthy ? ` · ${unhealthy} unhealthy` : ""}{disabled ? ` · ${disabled} disabled` : ""}</span>;
}

export { StatusBadge as ConnectorStatusBadge };
