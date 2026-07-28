import { expect, it, vi } from "vitest";

const redirect = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ redirect }));

import TenantApplicationRedirect from "./page";

it("server-redirects the legacy application route directly to Assistant", async () => {
  await TenantApplicationRedirect({
    params: Promise.resolve({ tenantSlug: "acme" }),
  });

  expect(redirect).toHaveBeenCalledWith("/t/acme/ai");
});
