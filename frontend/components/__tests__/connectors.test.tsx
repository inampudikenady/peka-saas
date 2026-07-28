import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectorDetail } from "@/components/connector-detail";
import { ConnectorInventory } from "@/components/connector-inventory";
import { ConnectorTable } from "@/components/connector-table";
import { RegistrationTokenTable } from "@/components/registration-token-table";
import { StatusBadge } from "@/components/status-badge";
import type { ConnectorDetail as Detail, ManagedConnector } from "@/lib/types";

const connector: ManagedConnector = {
  id: "c-1", tenant_id: "t-1", tenant_name: "Acme", tenant_slug: "acme", name: "Acme Files", instance_id: "i-1",
  version: "1.2.3", environment: "production", status: "connected", registered_at: "2026-07-20T10:00:00Z",
  last_heartbeat_at: "2026-07-20T10:01:00Z", last_seen_at: "2026-07-20T10:01:00Z", heartbeat_interval_seconds: 300,
  source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, retired_at: null,
  created_at: "2026-07-20T10:00:00Z", updated_at: "2026-07-20T10:01:00Z",
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

  it("shows every non-retired state by default and retired connectors on request", () => {
    const connectors = [
      { ...connector, id: "connected", name: "Connected connector", status: "connected" as const },
      { ...connector, id: "disconnected", name: "Disconnected connector", status: "disconnected" as const },
      { ...connector, id: "degraded", name: "Degraded connector", status: "degraded" as const },
      { ...connector, id: "retired", name: "Retired connector", status: "retired" as const, retired_at: "2026-07-20T12:00:00Z" },
    ];
    render(<ConnectorInventory connectors={connectors} detailBase="/connectors"/>);
    expect(screen.getByText("Connected connector")).toBeInTheDocument();
    expect(screen.getByText("Disconnected connector")).toBeInTheDocument();
    expect(screen.getByText("Degraded connector")).toBeInTheDocument();
    expect(screen.queryByText("Retired connector")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show retired connectors"));
    expect(screen.getByText("Retired connector")).toBeInTheDocument();
  });

  it("only renders retirement when mutation permission is supplied", () => {
    const { rerender } = render(<ConnectorTable connectors={[connector]} detailBase="/connectors"/>); expect(screen.queryByText("Retire")).not.toBeInTheDocument();
    rerender(<ConnectorTable connectors={[connector]} detailBase="/connectors" canRetire onRetire={() => undefined}/>); expect(screen.getByText("Retire")).toBeInTheDocument();
  });

  it("renders connector details, capabilities, heartbeat history, and events", () => {
    const detail: Detail = { ...connector, capabilities: ["filesystem_documents"], recent_heartbeats: [{ received_at: "2026-07-20T10:01:00Z", reported_at: "2026-07-20T10:01:00Z", version: "1.2.3", reported_status: "healthy", uptime_seconds: 42, source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, accepted: true }], recent_events: [{ event_type: "registered", occurred_at: "2026-07-20T10:00:00Z", detail: "Connector registered." }] };
    render(<ConnectorDetail connector={detail}/>); expect(screen.getByText("filesystem_documents")).toBeInTheDocument(); expect(screen.getByText("Accepted")).toBeInTheDocument(); expect(screen.getByText("Registered")).toBeInTheDocument();
  });

  it("renders the latest connector-owned name consistently", () => {
    const updated = { ...connector, name: "VITWO Production Connector" };
    const inventory = render(<ConnectorTable connectors={[updated]} detailBase="/connectors"/>);
    expect(screen.getByText("VITWO Production Connector")).toBeInTheDocument();
    inventory.unmount();
    render(<ConnectorDetail connector={{ ...updated, capabilities: [], recent_heartbeats: [], recent_events: [] }}/>);
    expect(screen.getAllByText("VITWO Production Connector")).not.toHaveLength(0);
  });

  it("does not present intended connector metadata in token management", () => {
    render(<RegistrationTokenTable items={[{
      id: "token-1", tenant_id: "t-1", expires_at: "2026-07-20T10:30:00Z", used_at: null,
      created_by_user_id: "user-1", created_at: "2026-07-20T10:00:00Z", revoked_at: null,
      intended_connector_name: "Legacy intended name", status: "active",
    }, {
      id: "token-2", tenant_id: "t-1", expires_at: "2026-07-20T10:30:00Z", used_at: "2026-07-20T10:01:00Z",
      created_by_user_id: "user-1", created_at: "2026-07-20T10:00:00Z", revoked_at: null,
      intended_connector_name: null, status: "used",
    }, {
      id: "token-3", tenant_id: "t-1", expires_at: "2026-07-20T09:30:00Z", used_at: null,
      created_by_user_id: "user-1", created_at: "2026-07-20T09:00:00Z", revoked_at: null,
      intended_connector_name: null, status: "expired",
    }, {
      id: "token-4", tenant_id: "t-1", expires_at: "2026-07-20T10:30:00Z", used_at: null,
      created_by_user_id: "user-1", created_at: "2026-07-20T10:00:00Z", revoked_at: "2026-07-20T10:02:00Z",
      intended_connector_name: null, status: "revoked",
    }]} canRevoke onRevoke={() => undefined}/>);
    expect(screen.getByText("Created")).toBeInTheDocument();
    expect(screen.queryByText(/Intended connector/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Legacy intended name")).not.toBeInTheDocument();
    expect(screen.queryByText("used")).not.toBeInTheDocument();
    expect(screen.queryByText("expired")).not.toBeInTheDocument();
    expect(screen.queryByText("revoked")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show inactive tokens"));
    expect(screen.getByText("used")).toBeInTheDocument();
    expect(screen.getByText("expired")).toBeInTheDocument();
    expect(screen.getByText("revoked")).toBeInTheDocument();
  });

  it("uses PEKA customer-facing connector terminology", () => {
    render(<StatusBadge status="connected"/>);
    expect(screen.getByText("Connected")).toHaveAttribute("title", expect.stringContaining("communicating with PEKA."));
    expect(screen.getByText("Connected")).not.toHaveAttribute("title", expect.stringContaining("PEKA SaaS"));
  });
});
