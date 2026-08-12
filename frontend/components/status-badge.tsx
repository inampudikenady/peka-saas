import { cn } from "@/lib/utils";
const labels: Record<string, string> = { connected: "Connected", in_sync: "Connected", degraded: "Degraded", out_of_sync: "Out of Sync", disconnected: "Disconnected", authentication_failed: "Authentication Failed", retired: "Retired" };
const explanations: Record<string, string> = {
  connected: "Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.", in_sync: "Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.",
  degraded: "The connector is reachable but one or more sources are unhealthy.", out_of_sync: "The last heartbeat is more than 1.5 expected intervals old.",
  disconnected: "No heartbeat has arrived for at least three expected intervals.", authentication_failed: "Repeated connector authentication attempts failed.", retired: "The connector was retired and can no longer authenticate.",
};
export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase(); const positive = ["active", "pending", "enabled", "operational", "connected", "in_sync"].includes(normalized);
  const amber = ["expired", "suspended", "disabled", "degraded", "out_of_sync"].includes(normalized); const red = ["disconnected", "authentication_failed"].includes(normalized);
  return <span title={explanations[normalized]} className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-medium", positive && "bg-peka-success-subtle text-peka-success", amber && "bg-peka-warning-subtle text-peka-warning", red && "bg-peka-danger-subtle text-peka-danger", !positive && !amber && !red && "bg-peka-app text-peka-secondary")}>{labels[normalized] ?? status}</span>;
}
