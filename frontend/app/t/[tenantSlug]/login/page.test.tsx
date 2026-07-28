import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Page from "./page";

const mocks = vi.hoisted(() => ({
  ssoOptions: vi.fn(),
  localLogin: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantSlug: "acme" }),
  useRouter: () => mocks,
}));
vi.mock("@/lib/api", () => ({
  tenantApi: {
    ssoOptions: mocks.ssoOptions,
    localLogin: mocks.localLogin,
  },
}));

beforeEach(() => {
  mocks.ssoOptions.mockReset();
  mocks.localLogin.mockReset();
  mocks.replace.mockReset();
});

it("labels an enabled Entra login without exposing configuration", async () => {
  mocks.ssoOptions.mockResolvedValue({
    provider: "microsoft_entra",
    enabled: true,
  });
  render(<Page />);
  const link = await screen.findByRole("link", {
    name: "Sign in with Microsoft",
  });
  expect(link).toHaveAttribute(
    "href",
    "/t/acme/api/v1/tenant/auth/login",
  );
  expect(screen.queryByText(/client-id|issuer/i)).not.toBeInTheDocument();
});

it("does not offer an SSO link when the tenant has not enabled it", async () => {
  mocks.ssoOptions.mockResolvedValue({
    provider: "generic_oidc",
    enabled: false,
  });
  render(<Page />);
  expect(await screen.findByRole("button", {
    name: "SSO is not configured",
  })).toBeDisabled();
  expect(screen.queryByRole("link", {
    name: /OpenID Connect/i,
  })).not.toBeInTheDocument();
});
