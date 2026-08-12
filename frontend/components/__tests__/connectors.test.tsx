import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConnectorDetail } from "@/components/connector-detail";
import { ConnectorInventory } from "@/components/connector-inventory";
import { ConnectorTable } from "@/components/connector-table";
import { RegistrationTokenTable } from "@/components/registration-token-table";
import { StatusBadge } from "@/components/status-badge";
import type { ConnectorDetail as Detail, ManagedConnector } from "@/lib/types";

const connector: ManagedConnector = {
  id: "c-1", tenant_id: "t-1", tenant_name: "Acme", tenant_slug: "acme", tenant_timezone: "UTC", name: "Acme Files", instance_id: "i-1",
  version: "1.2.3", environment: "production", status: "connected", registered_at: "2026-07-20T10:00:00Z",
  last_heartbeat_at: "2026-07-20T10:01:00Z", last_seen_at: "2026-07-20T10:01:00Z", heartbeat_interval_seconds: 300,
  source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, retired_at: null,
  local_knowledge_store_status: "healthy", knowledge_document_count: 124,
  knowledge_indexed_chunk_count: 18342, last_knowledge_index_activity_at: "2026-07-20T10:00:00Z",
  created_at: "2026-07-20T10:00:00Z", updated_at: "2026-07-20T10:01:00Z",
};

describe("connector presentation", () => {
  it.each([["connected", "Connected", "bg-peka-success-subtle"], ["degraded", "Degraded", "bg-peka-warning-subtle"], ["out_of_sync", "Out of Sync", "bg-peka-warning-subtle"], ["disconnected", "Disconnected", "bg-peka-danger-subtle"], ["authentication_failed", "Authentication Failed", "bg-peka-danger-subtle"], ["retired", "Retired", "bg-peka-app"]])("renders %s with text and semantic color", (status, label, style) => {
    render(<StatusBadge status={status}/>); expect(screen.getByText(label)).toHaveClass(style); expect(screen.getByText(label)).toHaveAttribute("title");
  });

  it("never displays the dormant in_sync compatibility value", () => {
    const view = render(<StatusBadge status="in_sync"/>); expect(view.container).toHaveTextContent("Connected"); expect(view.container).not.toHaveTextContent("In Sync");
  });

  it("renders only connector-level platform inventory actions", () => {
    render(<ConnectorTable connectors={[connector]} detailBase="/platform/connectors" platform onRefresh={() => undefined}/>);
    expect(screen.getByText("Connector")).toBeInTheDocument(); expect(screen.getAllByText("Acme Files")).not.toHaveLength(0);
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.queryByText("Open tenant portal")).not.toBeInTheDocument();
    expect(screen.queryByText("Details")).not.toBeInTheDocument();
    expect(screen.queryByText("Refresh Status")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Refresh status for Acme Files" })).not.toHaveLength(0);
    expect(screen.getAllByText("Refresh")).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Acme Files" }).every((link) => link.getAttribute("href") === "/platform/connectors/c-1")).toBe(true);
    expect(screen.getAllByRole("link", { name: "Acme Files" }).every((link) => link.classList.contains("focus-visible:ring-2"))).toBe(true);
    expect(screen.getAllByRole("button", { name: "Refresh status for Acme Files" }).every((button) => button.classList.contains("whitespace-nowrap"))).toBe(true);
    expect(screen.queryByText("Instance ID")).not.toBeInTheDocument();
    expect(screen.queryByText("Connector ID")).not.toBeInTheDocument();
    expect(screen.queryByText("i-1")).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveClass("table-fixed");
    expect(screen.getByTestId("connector-inventory-table")).toHaveClass("overflow-hidden");
  });

  it("removes registered-at metadata from the tenant inventory", () => {
    render(<ConnectorTable connectors={[connector]} detailBase="/connectors" onRefresh={() => undefined}/>);
    expect(screen.queryByText("Registered At")).not.toBeInTheDocument();
    expect(screen.queryByText("7/20/2026, 10:00:00 AM")).not.toBeInTheDocument();
    expect(screen.queryByText("Source summary")).not.toBeInTheDocument();
  });

  it("shows every non-retired state by default and retired connectors on request", () => {
    const connectors = [
      { ...connector, id: "connected", name: "Connected connector", status: "connected" as const },
      { ...connector, id: "disconnected", name: "Disconnected connector", status: "disconnected" as const },
      { ...connector, id: "degraded", name: "Degraded connector", status: "degraded" as const },
      { ...connector, id: "retired", name: "Retired connector", status: "retired" as const, retired_at: "2026-07-20T12:00:00Z" },
    ];
    render(<ConnectorInventory connectors={connectors} detailBase="/connectors"/>);
    expect(screen.getAllByText("Connected connector")).not.toHaveLength(0);
    expect(screen.getAllByText("Disconnected connector")).not.toHaveLength(0);
    expect(screen.getAllByText("Degraded connector")).not.toHaveLength(0);
    expect(screen.queryByText("Retired connector")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show retired connectors"));
    expect(screen.getAllByText("Retired connector")).not.toHaveLength(0);
  });

  it("only renders retirement when mutation permission is supplied", () => {
    const { rerender } = render(<ConnectorTable connectors={[connector]} detailBase="/connectors"/>); expect(screen.queryByText("Retire")).not.toBeInTheDocument();
    rerender(<ConnectorTable connectors={[connector]} detailBase="/connectors" canRetire onRefresh={() => undefined} onRetire={() => undefined}/>);
    expect(screen.queryByText("Details")).not.toBeInTheDocument();
    expect(screen.queryByText("Refresh Status")).not.toBeInTheDocument();
    expect(screen.getAllByText("Refresh")).not.toHaveLength(0);
    expect(screen.getAllByText("Retire")).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Acme Files" }).every((link) => link.getAttribute("href") === "/connectors/c-1")).toBe(true);
    expect(screen.getAllByRole("button", { name: "Refresh status for Acme Files" }).every((button) => button.parentElement?.classList.contains("flex-nowrap"))).toBe(true);
  });

  it("renders connector details, capabilities, heartbeat history, and events", () => {
    const detail: Detail = { ...connector, capabilities: ["filesystem_documents"], recent_heartbeats: [{ received_at: "2026-07-20T10:01:00Z", reported_at: "2026-07-20T10:01:00Z", version: "1.2.3", reported_status: "healthy", uptime_seconds: 42, source_total: 1, source_healthy: 1, source_unhealthy: 0, source_disabled: 0, accepted: true }], recent_events: [{ event_type: "registered", occurred_at: "2026-07-20T10:00:00Z", detail: "Connector registered." }] };
    render(<ConnectorDetail connector={detail}/>); expect(screen.getByText("Accepted")).toBeInTheDocument(); expect(screen.getByText("Registered")).toBeInTheDocument();
    expect(screen.getByText("Instance ID")).toBeInTheDocument();
    expect(screen.getByText("Connector ID")).toBeInTheDocument();
    expect(screen.getByText("Registered At")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy Instance ID" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy Connector ID" })).toBeInTheDocument();
    expect(screen.getByText("Integration health")).toBeInTheDocument();
    expect(screen.getByText(/Integration-specific status is not available/)).toBeInTheDocument();
    expect(screen.getByText("Local document management")).toBeInTheDocument();
    expect(screen.getByText("Local Knowledge Store")).toBeInTheDocument();
    expect(screen.getByText("18,342")).toBeInTheDocument();
    expect(screen.getByText("Reported")).toBeInTheDocument();
  });

  it("refreshes only the selected row and preserves the retired filter", async () => {
    let resolveRefresh: (value: ManagedConnector) => void = () => undefined;
    const refreshRequest = vi.fn((requestedConnector: ManagedConnector) => {
      void requestedConnector;
      return new Promise<ManagedConnector>((resolve) => { resolveRefresh = resolve; });
    });
    const retired = { ...connector, id: "c-retired", name: "Retired connector", retired_at: "2026-07-20T12:00:00Z", status: "retired" as const };
    const second = { ...connector, id: "c-2", name: "Second connector" };

    function Harness() {
      const [items, setItems] = useState([connector, second, retired]);
      return <ConnectorInventory connectors={items} detailBase="/connectors" onRefresh={async (item) => {
        const next = await refreshRequest(item);
        setItems((current) => current.map((candidate) => candidate.id === next.id ? next : candidate));
        return next;
      }}/>;
    }

    render(<Harness/>);
    fireEvent.click(screen.getByLabelText("Show retired connectors"));
    fireEvent.click(screen.getAllByLabelText("Refresh status for Acme Files")[0]);

    expect(refreshRequest).toHaveBeenCalledWith(connector);
    expect(screen.getAllByLabelText("Refresh status for Acme Files").every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getAllByLabelText("Refresh status for Acme Files").every((button) => button.getAttribute("aria-busy") === "true")).toBe(true);
    expect(screen.getAllByLabelText("Refresh status for Acme Files").every((button) => button.textContent?.includes("Refresh"))).toBe(true);
    expect(screen.getAllByLabelText("Refresh status for Second connector").every((button) => !button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getAllByTestId("refresh-spinner-c-1")).not.toHaveLength(0);

    await act(async () => resolveRefresh({ ...connector, version: "2.0.0", status: "degraded" }));
    await waitFor(() => expect(screen.getAllByText("2.0.0")).not.toHaveLength(0));
    expect(screen.getByRole("status")).toHaveTextContent("Acme Files status refreshed.");
    expect(screen.getByLabelText("Show retired connectors")).toBeChecked();
    expect(screen.getAllByText("Retired connector")).not.toHaveLength(0);
  });

  it("preserves connector data and reports a failed row refresh", async () => {
    const refreshRequest = vi.fn().mockRejectedValue(new Error("Refresh failed."));
    render(<ConnectorInventory connectors={[connector]} detailBase="/connectors" onRefresh={refreshRequest}/>);

    fireEvent.click(screen.getAllByLabelText("Refresh status for Acme Files")[0]);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Refresh failed."));
    expect(screen.getAllByText("1.2.3")).not.toHaveLength(0);
    expect(screen.getAllByText("Connected")).not.toHaveLength(0);
  });

  it("renders the latest connector-owned name consistently", () => {
    const updated = { ...connector, name: "VITWO Production Connector" };
    const inventory = render(<ConnectorTable connectors={[updated]} detailBase="/connectors"/>);
    expect(screen.getAllByText("VITWO Production Connector")).not.toHaveLength(0);
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
