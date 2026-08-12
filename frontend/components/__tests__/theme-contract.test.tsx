import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { ProfileMenu } from "@/components/profile-menu";
import shellSource from "@/components/app-shell.tsx?raw";
import platformSource from "@/components/platform-shell.tsx?raw";
import tenantSource from "@/components/tenant-shell.tsx?raw";

const tokenSource = readFileSync(join(process.cwd(), "app/peka-tokens.css"), "utf8");

describe("unified PEKA theme contract", () => {
  it("defines the semantic tokens used by every role shell", () => {
    for (const token of [
      "--peka-bg-app", "--peka-bg-surface", "--peka-bg-sidebar",
      "--peka-bg-sidebar-hover", "--peka-bg-sidebar-active",
      "--peka-text-primary", "--peka-text-secondary", "--peka-text-muted",
      "--peka-text-on-dark", "--peka-border-default", "--peka-border-strong",
      "--peka-primary", "--peka-success", "--peka-warning", "--peka-danger",
      "--peka-info", "--peka-focus-ring", "--peka-shadow-card",
    ]) expect(tokenSource).toContain(token);
    expect(shellSource).toContain("bg-peka-sidebar");
    expect(shellSource).toContain("bg-peka-app");
  });

  it("routes platform and tenant roles through the same application shell", () => {
    expect(platformSource).toContain("<AppShell");
    expect(tenantSource).toContain("<AppShell");
    expect(platformSource).toContain('user.role === "platform_admin"');
    expect(tenantSource).toContain('user.role === "tenant_admin"');
  });

  it("keeps the user menu closed until its accessible trigger is activated", () => {
    render(<ProfileMenu label="Kenady" profileHref="/profile" onLogout={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Open user menu" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});
