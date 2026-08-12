import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NewTenantPage from "@/app/platform/tenants/new/page";
import {
  browserTimezone,
  TimezoneSelector,
} from "@/components/timezone-selector";
import { platformApi } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("@/components/platform-shell", () => ({
  PlatformShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/lib/api", () => ({
  platformApi: {
    timezones: vi.fn(),
    createTenant: vi.fn(),
  },
}));

const catalog = [
  "America/New_York",
  "Asia/Kolkata",
  "Australia/Sydney",
  "Europe/London",
  "UTC",
];

describe("timezone selector", () => {
  beforeEach(() => {
    vi.mocked(platformApi.timezones).mockResolvedValue({
      timezones: catalog,
      aliases: { "Asia/Calcutta": "Asia/Kolkata" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the full API catalog and searches canonical city names", async () => {
    render(<TimezoneSelector aria-label="Timezone" />);
    const input = screen.getByRole("combobox", { name: "Timezone" });

    fireEvent.focus(input);
    expect(await screen.findByRole("option", { name: "Asia/Kolkata" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Europe/London" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "America/New_York" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Australia/Sydney" })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "London" } });
    expect(screen.getByRole("option", { name: "Europe/London" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Asia/Kolkata" })).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "New York" } });
    expect(screen.getByRole("option", { name: "America/New_York" })).toBeInTheDocument();
  });

  it("selects a searched timezone without exposing a deprecated current alias", async () => {
    function Harness() {
      const [value, setValue] = useState("Asia/Calcutta");
      return (
        <TimezoneSelector
          aria-label="Timezone"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      );
    }

    render(<Harness />);
    const input = screen.getByRole("combobox", { name: "Timezone" });
    expect(input).toHaveValue("Asia/Kolkata");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Sydney" } });
    fireEvent.click(await screen.findByRole("option", { name: "Australia/Sydney" }));
    expect(input).toHaveValue("Australia/Sydney");
  });

  it("normalizes the deprecated browser alias", () => {
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      locale: "en-US",
      calendar: "gregory",
      numberingSystem: "latn",
      timeZone: "Asia/Calcutta",
      year: "numeric",
      month: "numeric",
      day: "numeric",
    });
    expect(browserTimezone()).toBe("Asia/Kolkata");
  });

  it("uses the browser timezone as the new-tenant default", async () => {
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      locale: "en-US",
      calendar: "gregory",
      numberingSystem: "latn",
      timeZone: "Europe/London",
      year: "numeric",
      month: "numeric",
      day: "numeric",
    });
    render(<NewTenantPage />);
    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("Europe/London");
    });
  });
});
