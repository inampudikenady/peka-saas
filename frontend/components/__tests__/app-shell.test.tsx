import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/acme/ai",
}));
vi.mock("@/components/profile-menu", () => ({
  ProfileMenu: ({ label }: { label: string }) => <div>{label}</div>,
}));

const storedPreferences = new Map<string, string>();

beforeEach(() => {
  storedPreferences.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storedPreferences.get(key) ?? null,
    setItem: (key: string, value: string) => storedPreferences.set(key, value),
    removeItem: (key: string) => storedPreferences.delete(key),
    clear: () => storedPreferences.clear(),
  });
});

function TestShell({ context = "acme" }: { context?: string }) {
  return (
    <AppShell
      title="Assistant"
      subtitle="Acme · Tenant user"
      items={[{ label: "Assistant", href: "/t/acme/ai" }]}
      userLabel="User"
      profileHref="/t/acme/profile"
      onLogout={vi.fn()}
      collapsibleSidebar
      sidebarPreferenceKey="peka:test-sidebar"
      navigationContextKey={context}
      sidebarTop={() => <button type="button">New chat</button>}
      collapsedSidebarTop={() => (
        <button type="button" aria-label="New chat">+</button>
      )}
      sidebarContent={() => (
        <section aria-label="Conversation history">Private conversation</section>
      )}
    >
      <p>Conversation area</p>
    </AppShell>
  );
}

function renderShell() {
  return render(<TestShell />);
}

it("collapses the dark sidebar without rendering conversation cards", async () => {
  renderShell();
  const sidebar = screen.getByRole("complementary", { name: "Primary navigation" });
  expect(sidebar).toHaveAttribute("data-collapsed", "false");
  expect(screen.getByText("Private conversation")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  expect(sidebar).toHaveAttribute("data-collapsed", "true");
  expect(localStorage.getItem("peka:test-sidebar")).toBe("true");
  expect(screen.getByRole("tooltip", { name: "Assistant" })).toBeInTheDocument();
  expect(screen.getByRole("tooltip", { name: "Expand sidebar" })).toBeInTheDocument();

  // The history remains available to a mobile drawer, but desktop CSS hides it.
  expect(screen.getByLabelText("Conversation history").parentElement).toHaveClass("md:hidden");

  fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
  expect(sidebar).toHaveAttribute("data-collapsed", "false");
  expect(localStorage.getItem("peka:test-sidebar")).toBe("false");
});

it("restores the safe local collapsed preference", async () => {
  localStorage.setItem("peka:test-sidebar", "true");
  renderShell();
  await waitFor(() =>
    expect(screen.getByLabelText("Primary navigation")).toHaveAttribute(
      "data-collapsed",
      "true",
    ),
  );
});

it("uses the sidebar as a mobile drawer and closes it after navigation", () => {
  renderShell();
  const sidebar = screen.getByLabelText("Primary navigation");
  expect(sidebar).toHaveClass("-translate-x-full");

  fireEvent.click(screen.getByRole("button", { name: "Open navigation drawer" }));
  expect(sidebar).toHaveClass("translate-x-0");
  expect(screen.getByRole("button", { name: "Close navigation drawer" })).toBeInTheDocument();

  const link = screen.getByRole("link", { name: "Assistant" });
  link.addEventListener("click", (event) => event.preventDefault());
  fireEvent.click(link);
  expect(sidebar).toHaveClass("-translate-x-full");
});

it("closes the mobile drawer when tenant context changes", () => {
  const view = render(<TestShell context="acme" />);
  const sidebar = screen.getByLabelText("Primary navigation");
  fireEvent.click(screen.getByRole("button", { name: "Open navigation drawer" }));
  expect(sidebar).toHaveClass("translate-x-0");

  view.rerender(<TestShell context="beta" />);
  expect(sidebar).toHaveClass("-translate-x-full");
});
