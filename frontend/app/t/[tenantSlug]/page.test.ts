import { expect, it, vi } from "vitest";

const redirect = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ redirect }));

import TenantRootPage from "./page";

it("server-redirects the tenant root directly to Assistant", async () => {
  await TenantRootPage({
    params: Promise.resolve({ tenantSlug: "acme" }),
  });

  expect(redirect).toHaveBeenCalledWith("/t/acme/ai");
});
