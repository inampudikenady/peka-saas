import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ConnectorDetail, ManagedConnector } from "@/lib/types";
import Page from "./page";

const { listConnectors, getConnector } = vi.hoisted(() => ({
  listConnectors: vi.fn(),
  getConnector: vi.fn(),
}));

vi.mock("@/components/platform-shell", () => ({
  PlatformShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/lib/api", () => ({
  platformApi: { connectors: listConnectors, connector: getConnector },
}));

const connector: ManagedConnector = {
  id: "connector-1", tenant_id: "tenant-1", tenant_name: "Acme", tenant_slug: "acme", tenant_timezone: "UTC",
  name: "Acme Connector", instance_id: "instance-1", version: "1.0.0", environment: "production", status: "connected",
  registered_at: "2026-08-01T10:00:00Z", last_heartbeat_at: "2026-08-01T10:05:00Z", last_seen_at: "2026-08-01T10:05:00Z",
  heartbeat_interval_seconds: 300, source_total: 2, source_healthy: 2, source_unhealthy: 0, source_disabled: 0,
  retired_at: null, created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:05:00Z",
};

beforeEach(() => {
  listConnectors.mockReset().mockResolvedValue([connector]);
  getConnector.mockReset().mockResolvedValue({
    ...connector,
    version: "1.1.0",
    status: "degraded",
    capabilities: [], recent_heartbeats: [], recent_events: [],
  } satisfies ConnectorDetail);
});

it("refreshes a platform connector through the detail API without reloading the page", async () => {
  render(<Page/>);
  await screen.findAllByText("Acme Connector");

  expect(screen.queryByText("Details")).not.toBeInTheDocument();
  expect(screen.queryByText("Refresh Status")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Acme Connector" }).every((link) => link.getAttribute("href") === "/platform/connectors/connector-1")).toBe(true);
  expect(screen.getAllByText("Refresh")).not.toHaveLength(0);

  fireEvent.click(screen.getAllByLabelText("Refresh status for Acme Connector")[0]);

  await waitFor(() => expect(getConnector).toHaveBeenCalledWith("connector-1"));
  await waitFor(() => expect(screen.getAllByText("1.1.0")).not.toHaveLength(0));
  expect(screen.getAllByText("Degraded")).not.toHaveLength(0);
  expect(screen.getByRole("status")).toHaveTextContent("Acme Connector status refreshed.");
  expect(screen.queryByText("Open tenant portal")).not.toBeInTheDocument();
  expect(listConnectors).toHaveBeenCalledTimes(1);
});
