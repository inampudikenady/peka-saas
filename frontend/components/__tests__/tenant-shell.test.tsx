import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { TenantShell } from "@/components/tenant-shell";
import type { TenantMe } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/components/app-shell", () => ({
  AppShell: ({
    items,
    children,
    sidebarTop,
    sidebarContent,
  }: {
    items: { label: string }[];
    children: React.ReactNode;
    sidebarTop?: (controls: { closeMobile: () => void }) => React.ReactNode;
    sidebarContent?: (controls: { closeMobile: () => void }) => React.ReactNode;
  }) => (
    <div>
      <nav>{items.map((item) => <span key={item.label}>{item.label}</span>)}</nav>
      {sidebarTop?.({ closeMobile: vi.fn() })}
      {sidebarContent?.({ closeMobile: vi.fn() })}
      {children}
    </div>
  ),
}));

const user: TenantMe = {
  id: "u",
  email: "u@acme.test",
  full_name: "User",
  auth_source: "sso",
  tenant_id: "t",
  tenant_slug: "acme",
  tenant_name: "Acme",
  role: "tenant_user",
  username: null,
  is_active: true,
  last_login_at: null,
};

it("does not show redundant navigation to a normal tenant user", () => {
  render(
    <TenantShell
      slug="acme"
      title="Assistant"
      user={user}
      aiSidebarTop={() => <button type="button">New chat</button>}
      aiSidebarContent={() => <p>Private history</p>}
    >
      <p>Content</p>
    </TenantShell>,
  );
  expect(screen.queryByText("Assistant")).not.toBeInTheDocument();
  expect(screen.queryByText("Connectors")).not.toBeInTheDocument();
  expect(screen.queryByText("Administration")).not.toBeInTheDocument();
  expect(screen.getByText("New chat")).toBeInTheDocument();
  expect(screen.getByText("Private history")).toBeInTheDocument();
});

it("keeps connector and administration navigation for a tenant administrator", () => {
  render(
    <TenantShell
      slug="acme"
      title="Test"
      user={{ ...user, role: "tenant_admin" }}
    >
      <p>Content</p>
    </TenantShell>,
  );
  expect(screen.getByText("Assistant")).toBeInTheDocument();
  expect(screen.getByText("Connectors")).toBeInTheDocument();
  expect(screen.getByText("Administration")).toBeInTheDocument();
});

it("shows admin history only in the Assistant context", () => {
  const admin = { ...user, role: "tenant_admin" as const };
  const assistant = render(
    <TenantShell
      slug="acme"
      title="Assistant"
      user={admin}
      aiSidebarTop={() => <button type="button">New chat</button>}
      aiSidebarContent={() => <p>Private history</p>}
    >
      <p>Conversation</p>
    </TenantShell>,
  );
  expect(screen.getByText("Private history")).toBeInTheDocument();
  expect(screen.getByText("New chat")).toBeInTheDocument();

  assistant.rerender(
    <TenantShell slug="acme" title="Connectors" user={admin} adminOnly>
      <p>Connector inventory</p>
    </TenantShell>,
  );
  expect(screen.queryByText("Private history")).not.toBeInTheDocument();
  expect(screen.queryByText("New chat")).not.toBeInTheDocument();
  expect(screen.getByText("Connector inventory")).toBeInTheDocument();

  assistant.rerender(
    <TenantShell slug="acme" title="Administration" user={admin} adminOnly>
      <p>Administration settings</p>
    </TenantShell>,
  );
  expect(screen.queryByText("Private history")).not.toBeInTheDocument();
  expect(screen.queryByText("New chat")).not.toBeInTheDocument();
  expect(screen.getByText("Administration settings")).toBeInTheDocument();
});

it("blocks a normal tenant user from an admin-only tenant page", () => {
  render(
    <TenantShell slug="acme" title="Connectors" user={user} adminOnly>
      <p>Connector inventory</p>
    </TenantShell>,
  );
  expect(screen.getByRole("heading", { name: "Access forbidden" })).toBeInTheDocument();
  expect(screen.queryByText("Connector inventory")).not.toBeInTheDocument();
});
