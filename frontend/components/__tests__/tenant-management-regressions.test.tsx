import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ManageTenantPage from "@/app/platform/administration/tenant-management/[slug]/page";
import TenantDetailPage from "@/app/platform/tenants/[slug]/page";
import TenantsPage from "@/app/platform/tenants/page";
import { usePlatformUser } from "@/hooks/use-platform-user";
import { platformApi } from "@/lib/api";
import type { PlatformRole, Tenant, TenantAdminInvite } from "@/lib/types";

const replace = vi.fn();
const clipboardWrite = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "acme" }),
  useRouter: () => ({ replace }),
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("@/components/platform-shell", () => ({
  PlatformShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/timezone-selector", () => ({
  canonicalTimezone: (value: string) => value === "Asia/Calcutta" ? "Asia/Kolkata" : value,
  TimezoneSelector: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));
vi.mock("@/hooks/use-platform-user", () => ({ usePlatformUser: vi.fn() }));
vi.mock("@/lib/api", () => ({
  platformApi: {
    tenants: vi.fn(),
    tenant: vi.fn(),
    tenantInvite: vi.fn(),
    tenantSummary: vi.fn(),
    tenantAuditEvents: vi.fn(),
    updateTenant: vi.fn(),
    updateInviteRecipient: vi.fn(),
    regenerateInvite: vi.fn(),
    deactivateTenant: vi.fn(),
    activateTenant: vi.fn(),
    deleteTenant: vi.fn(),
  },
}));

const activeTenant: Tenant = {
  id: "tenant-1",
  slug: "acme",
  name: "Acme",
  display_name: "Acme",
  status: "active",
  primary_domain: null,
  subdomain: "acme.example.test",
  tenant_url: "/t/acme",
  timezone: "Asia/Kolkata",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};
const pendingInvite: TenantAdminInvite = {
  email: "admin@acme.test",
  full_name: "Acme Admin",
  expires_at: "2026-08-01T00:00:00Z",
  used_at: null,
  status: "pending",
  setup_link: null,
};
const usedInvite: TenantAdminInvite = {
  ...pendingInvite,
  used_at: "2026-07-20T10:00:00Z",
  status: "used",
};

function identity(role: PlatformRole) {
  vi.mocked(usePlatformUser).mockReturnValue({
    user: {
      id: "user-1",
      username: "operator",
      email: "operator@example.test",
      full_name: "Platform Operator",
      role,
      is_active: true,
      last_login_at: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    error: "",
  });
}

describe("platform tenant navigation and management", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });
    clipboardWrite.mockResolvedValue(undefined);
    identity("platform_admin");
    vi.mocked(platformApi.tenants).mockResolvedValue([activeTenant]);
    vi.mocked(platformApi.tenant).mockResolvedValue(activeTenant);
    vi.mocked(platformApi.tenantInvite).mockResolvedValue(pendingInvite);
    vi.mocked(platformApi.tenantSummary).mockResolvedValue({
      sso_enabled: false,
      sso_redirect_uri: null,
      local_admin_active: false,
      active_user_count: 0,
      administrator_count: 0,
      connector_count: 0,
    });
    vi.mocked(platformApi.tenantAuditEvents).mockResolvedValue([]);
    vi.mocked(platformApi.deactivateTenant).mockResolvedValue({
      ...activeTenant,
      status: "suspended",
    });
    vi.mocked(platformApi.activateTenant).mockResolvedValue(activeTenant);
  });

  it("keeps management out of the shared list and hides the detail link from ReadOnly", async () => {
    identity("platform_readonly");
    const list = render(<TenantsPage />);
    expect((await screen.findAllByRole("link", { name: "Acme" })).every((link) => link.getAttribute("href") === "/platform/tenants/acme")).toBe(true);
    expect(screen.getAllByRole("link", { name: "Open Acme portal: /t/acme" })).not.toHaveLength(0);
    expect(screen.queryByRole("link", { name: /manage/i })).not.toBeInTheDocument();
    expect(platformApi.tenantInvite).not.toHaveBeenCalled();
    list.unmount();

    render(<TenantDetailPage />);
    expect(await screen.findByText("Tenant information")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manage tenant" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open portal" })).toBeInTheDocument();
  });

  it("renders a compact four-column tenant directory with linked URLs and copy icons", async () => {
    render(<TenantsPage />);
    const tenantLinks = await screen.findAllByRole("link", { name: "Acme" });
    const portalLinks = screen.getAllByRole("link", { name: "Open Acme portal: /t/acme" });

    expect(tenantLinks.every((link) => link.getAttribute("href") === "/platform/tenants/acme")).toBe(true);
    expect(tenantLinks.every((link) => link.classList.contains("focus-visible:ring-2"))).toBe(true);
    expect(screen.queryByRole("link", { name: "Details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open portal" })).not.toBeInTheDocument();
    expect(portalLinks.every((link) => link.getAttribute("href") === "/t/acme")).toBe(true);
    expect(portalLinks.every((link) => link.getAttribute("target") === "_blank")).toBe(true);
    expect(portalLinks.every((link) => link.getAttribute("rel") === "noopener noreferrer")).toBe(true);
    expect(portalLinks.every((link) => link.getAttribute("title") === "/t/acme")).toBe(true);
    expect(screen.queryByRole("columnheader", { name: "Setup" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Timezone" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveClass("table-fixed");
    expect(screen.getByTestId("tenant-inventory")).toHaveClass("overflow-hidden");

    const copyButtons = screen.getAllByRole("button", { name: "Copy tenant URL" });
    expect(copyButtons.every((button) => button.classList.contains("w-8"))).toBe(true);
    expect(copyButtons.every((button) => button.getAttribute("title") === "Copy tenant URL")).toBe(true);
    fireEvent.click(copyButtons[0]);
    await waitFor(() => expect(clipboardWrite).toHaveBeenCalledWith("/t/acme"));
  });

  it("keeps timezone and initial-administrator invitation state on tenant details", async () => {
    vi.mocked(platformApi.tenantInvite).mockResolvedValue(usedInvite);
    render(<TenantDetailPage />);

    expect(await screen.findByText("Initial administrator invitation status")).toBeInTheDocument();
    expect(screen.getByText("Asia/Kolkata")).toBeInTheDocument();
    expect(screen.getByText("tenant-1")).toBeInTheDocument();
    expect(screen.getByText("used")).toBeInTheDocument();
  });

  it("shows the administration link to Platform Admin on tenant details", async () => {
    render(<TenantDetailPage />);
    expect(await screen.findByRole("link", { name: "Manage tenant" })).toHaveAttribute(
      "href",
      "/platform/administration/tenant-management/acme",
    );
  });

  it("shows valid bootstrap actions only while setup is pending", async () => {
    render(<ManageTenantPage />);
    expect(await screen.findByText("Initial administrator invitation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update recipient" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate setup invitation" })).toBeInTheDocument();
  });

  it("replaces a used invitation with compact completed setup status", async () => {
    vi.mocked(platformApi.tenantInvite).mockResolvedValue(usedInvite);
    render(<ManageTenantPage />);
    expect(await screen.findByText("Tenant setup")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Acme Admin · admin@acme.test")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /regenerate/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Initial administrator email")).not.toBeInTheDocument();
    expect(screen.queryByText(/manage the tenant administrators below/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Tenant administrators")).not.toBeInTheDocument();
  });

  it("uses confirm/cancel lifecycle controls without typed slug confirmation", async () => {
    render(<ManageTenantPage />);
    const deactivate = await screen.findByRole("button", { name: "Deactivate tenant" });
    expect(screen.queryByLabelText("Lifecycle confirmation")).not.toBeInTheDocument();
    fireEvent.click(deactivate);
    expect(screen.getByRole("dialog", { name: "Deactivate tenant?" })).toBeInTheDocument();
    expect(screen.getByText(/access and routing will be disabled/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(platformApi.deactivateTenant).toHaveBeenCalledWith("acme"));
  });

  it("disables deletion while active and enables slug confirmation after deactivation", async () => {
    const view = render(<ManageTenantPage />);
    const disabledDelete = await screen.findByRole("button", { name: "Delete tenant" });
    expect(disabledDelete).toBeDisabled();
    expect(screen.getByText("Deactivate the tenant before permanent deletion.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tenant slug confirmation")).not.toBeInTheDocument();
    view.unmount();

    vi.mocked(platformApi.tenant).mockResolvedValue({ ...activeTenant, status: "suspended" });
    render(<ManageTenantPage />);
    expect(await screen.findByRole("button", { name: "Reactivate tenant" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete tenant" }));
    const slugInput = screen.getByLabelText("Tenant slug confirmation");
    const permanentDelete = screen.getByRole("button", { name: "Delete permanently" });
    expect(slugInput).toBeInTheDocument();
    expect(permanentDelete).toBeDisabled();
    fireEvent.change(slugInput, { target: { value: "wrong" } });
    expect(permanentDelete).toBeDisabled();
    fireEvent.change(slugInput, { target: { value: "acme" } });
    expect(permanentDelete).toBeEnabled();
  });

  it("confirms reactivation and restores the active lifecycle state", async () => {
    vi.mocked(platformApi.tenant).mockResolvedValue({ ...activeTenant, status: "suspended" });
    render(<ManageTenantPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Reactivate tenant" }));
    expect(screen.getByRole("dialog", { name: "Reactivate tenant?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(platformApi.activateTenant).toHaveBeenCalledWith("acme"));
  });
});
