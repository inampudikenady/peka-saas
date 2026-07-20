import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectorDetail } from "@/components/connector-detail";
import { ConnectorTable } from "@/components/connector-table";
import { StatusBadge } from "@/components/status-badge";
import type { ConnectorDetail as Detail, ManagedConnector } from "@/lib/types";

const connector: ManagedConnector = {
  id: "c-1", tenant_id: "t-1", tenant_name: "Acme", tenant_slug: "acme", name: "Acme Files", instance_id: "i-1",
  version: "1.2.3", environment: "production", status: "connected", registered_at: "2026-07-20T10:00:00Z",
  last_heartbeat_at: "2026-07-20T10:01:00Z", last_seen_at: "2026-07-20T10:01:00Z", heartbeat_interval_seconds: 300,
  source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, retired_at: null,
};

describe("connector presentation", () => {
  it.each([["connected", "Connected", "bg-emerald-100"], ["degraded", "Degraded", "bg-amber-100"], ["out_of_sync", "Out of Sync", "bg-amber-100"], ["disconnected", "Disconnected", "bg-red-100"], ["authentication_failed", "Authentication Failed", "bg-red-100"], ["retired", "Retired", "bg-slate-100"]])("renders %s with text and semantic color", (status, label, style) => {
    render(<StatusBadge status={status}/>); expect(screen.getByText(label)).toHaveClass(style); expect(screen.getByText(label)).toHaveAttribute("title");
  });

  it("never displays the dormant in_sync compatibility value", () => {
    const view = render(<StatusBadge status="in_sync"/>); expect(view.container).toHaveTextContent("Connected"); expect(view.container).not.toHaveTextContent("In Sync");
  });

  it("renders the platform inventory columns and authorized portal action", () => {
    render(<ConnectorTable connectors={[connector]} detailBase="/platform/connectors" platform/>);
    expect(screen.getByText("Connector Name")).toBeInTheDocument(); expect(screen.getByText("Acme Files")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument(); expect(screen.getByText("Open tenant portal")).toHaveAttribute("href", "/t/acme");
  });

  it("only renders retirement when mutation permission is supplied", () => {
    const { rerender } = render(<ConnectorTable connectors={[connector]} detailBase="/connectors"/>); expect(screen.queryByText("Retire")).not.toBeInTheDocument();
    rerender(<ConnectorTable connectors={[connector]} detailBase="/connectors" canRetire onRetire={() => undefined}/>); expect(screen.getByText("Retire")).toBeInTheDocument();
  });

  it("renders connector details, capabilities, heartbeat history, and events", () => {
    const detail: Detail = { ...connector, capabilities: ["filesystem_documents"], recent_heartbeats: [{ received_at: "2026-07-20T10:01:00Z", reported_at: "2026-07-20T10:01:00Z", version: "1.2.3", reported_status: "healthy", uptime_seconds: 42, source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, accepted: true }], recent_events: [{ event_type: "registered", occurred_at: "2026-07-20T10:00:00Z", detail: "Connector registered." }] };
    render(<ConnectorDetail connector={detail}/>); expect(screen.getByText("filesystem_documents")).toBeInTheDocument(); expect(screen.getByText("Accepted")).toBeInTheDocument(); expect(screen.getByText("Registered")).toBeInTheDocument();
  });
});
