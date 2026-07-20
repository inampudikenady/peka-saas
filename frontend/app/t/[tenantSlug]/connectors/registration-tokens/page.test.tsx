import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Page from "./page";

const createRegistrationToken = vi.fn();
vi.mock("next/navigation", () => ({ useParams: () => ({ tenantSlug: "acme" }) }));
vi.mock("@/hooks/use-tenant-user", () => ({ useTenantUser: () => ({ user: { role: "tenant_admin", tenant_name: "Acme", full_name: "Admin", auth_source: "local" } }) }));
vi.mock("@/lib/api", () => ({ tenantApi: { registrationTokens: vi.fn().mockResolvedValue([]), createRegistrationToken: (...args: unknown[]) => createRegistrationToken(...args), revokeRegistrationToken: vi.fn() } }));
vi.mock("@/components/tenant-shell", () => ({ TenantShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

describe("registration token generation", () => {
  beforeEach(() => { createRegistrationToken.mockReset(); });
  it("shows the raw token once with a copy action", async () => {
    createRegistrationToken.mockResolvedValue({ id: "token-1", tenant_id: "tenant-1", registration_token: "peka_reg_one_time", expires_at: "2026-07-20T11:00:00Z", created_at: "2026-07-20T10:30:00Z", used_at: null, revoked_at: null, created_by_user_id: "user-1", intended_connector_name: "Acme Files", status: "active" });
    render(<Page/>); fireEvent.change(screen.getByPlaceholderText("Intended connector name (optional)"), { target: { value: "Acme Files" } }); fireEvent.click(screen.getByRole("button", { name: "Generate token" }));
    await waitFor(() => expect(screen.getByText("peka_reg_one_time")).toBeInTheDocument()); expect(screen.getByText("Copy")).toBeInTheDocument(); expect(createRegistrationToken).toHaveBeenCalledWith("acme", "Acme Files");
  });
});
