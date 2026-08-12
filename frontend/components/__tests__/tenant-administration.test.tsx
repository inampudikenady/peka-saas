import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TenantAdministration, tenantAdministrationTabs } from "@/components/tenant-administration";

vi.mock("next/navigation", () => ({ useParams: () => ({ tenantSlug: "acme" }) }));
vi.mock("@/hooks/use-tenant-user", () => ({ useTenantUser: () => ({ user: { role: "tenant_admin" } }) }));
vi.mock("@/components/tenant-shell", () => ({ TenantShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

describe("tenant administration navigation", () => {
  it("does not include a duplicate Connectors tab", () => {
    render(<TenantAdministration title="Administration"><p>Content</p></TenantAdministration>);
    expect(tenantAdministrationTabs.map(([label]) => label)).toEqual(["Users", "Authentication", "Tenant settings", "Audit"]);
    expect(screen.queryByRole("link", { name: "Connectors" })).not.toBeInTheDocument();
  });
});
