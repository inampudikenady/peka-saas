import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (...args: unknown[]) => redirect(...args) }));

import Page from "./page";
import { primaryConnectorsPath } from "@/lib/tenant-navigation";

describe("legacy administration connector route", () => {
  it("redirects bookmarks to the primary connector inventory", async () => {
    expect(primaryConnectorsPath("acme")).toBe("/t/acme/connectors");
    await Page({ params: Promise.resolve({ tenantSlug: "acme" }) });
    expect(redirect).toHaveBeenCalledWith("/t/acme/connectors");
  });
});
