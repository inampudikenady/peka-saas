import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ConnectorDetail, ManagedConnector } from "@/lib/types";
import Page from "./page";

const { listConnectors, getConnector, retireConnector } = vi.hoisted(() => ({
  listConnectors: vi.fn(),
  getConnector: vi.fn(),
  retireConnector: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ tenantSlug: "acme" }) }));
vi.mock("@/hooks/use-tenant-user", () => ({
  useTenantUser: () => ({ user: { id: "user-1", role: "tenant_admin", full_name: "Admin" }, error: "" }),
}));
vi.mock("@/components/tenant-shell", () => ({
  TenantShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/lib/api", () => ({
  tenantApi: {
    connectors: listConnectors,
    connector: getConnector,
    retireConnector,
  },
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
    capabilities: [], recent_heartbeats: [], recent_events: [],
  } satisfies ConnectorDetail);
  retireConnector.mockReset();
  retireConnector.mockResolvedValue({
    ...connector,
    status: "retired",
    retired_at: "2026-08-01T10:10:00Z",
  });
});

it("refreshes tenant connector status without changing retirement behavior", async () => {
  render(<Page/>);
  await screen.findAllByText("Acme Connector");

  expect(screen.queryByText("Details")).not.toBeInTheDocument();
  expect(screen.queryByText("Refresh Status")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Acme Connector" }).every((link) => link.getAttribute("href") === "/t/acme/connectors/connector-1")).toBe(true);
  expect(screen.getAllByText("Refresh")).not.toHaveLength(0);

  fireEvent.click(screen.getAllByLabelText("Refresh status for Acme Connector")[0]);

  await waitFor(() => expect(getConnector).toHaveBeenCalledWith("acme", "connector-1"));
  await waitFor(() => expect(screen.getAllByText("1.1.0")).not.toHaveLength(0));
  expect(screen.queryByText("Source summary")).not.toBeInTheDocument();
  expect(screen.getAllByText("Retire")).not.toHaveLength(0);
  expect(retireConnector).not.toHaveBeenCalled();
});

it("preserves the existing confirmed retirement flow", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<Page/>);
  await screen.findAllByText("Acme Connector");

  fireEvent.click(screen.getAllByRole("button", { name: "Retire" })[0]);

  await waitFor(() => expect(retireConnector).toHaveBeenCalledWith("acme", "connector-1"));
  expect(confirm).toHaveBeenCalledWith("Retire Acme Connector? It will no longer be able to authenticate.");
  confirm.mockRestore();
});
