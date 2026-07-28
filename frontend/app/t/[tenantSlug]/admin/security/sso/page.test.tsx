import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Page from "./page";

const mocks = vi.hoisted(() => ({
  getSSO: vi.fn(),
  updateSSO: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantSlug: "acme" }),
  useRouter: () => mocks,
}));
vi.mock("@/hooks/use-tenant-user", () => ({
  useTenantUser: () => ({
    user: {
      role: "tenant_admin",
      tenant_name: "Acme",
      full_name: "Admin",
    },
    error: "",
  }),
}));
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
  tenantApi: {
    getSSO: mocks.getSSO,
    updateSSO: mocks.updateSSO,
  },
}));
vi.mock("@/components/tenant-shell", () => ({
  TenantShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

beforeEach(() => {
  mocks.getSSO.mockReset();
  mocks.updateSSO.mockReset();
  mocks.replace.mockReset();
  mocks.getSSO.mockResolvedValue({
    provider: "microsoft_entra",
    entra_tenant_id: "11111111-1111-4111-8111-111111111111",
    issuer_url:
      "https://login.microsoftonline.com/"
      + "11111111-1111-4111-8111-111111111111/v2.0",
    client_id: "client-id",
    client_secret_configured: true,
    redirect_uri: "https://acme.example/callback",
    enabled: false,
  });
});

it("shows only provider inputs and deliberately replaces an existing secret", async () => {
  render(<Page />);

  expect(await screen.findByLabelText("Directory (tenant) ID")).toHaveValue(
    "11111111-1111-4111-8111-111111111111",
  );
  expect(screen.getByLabelText("Client ID")).toHaveValue("client-id");
  expect(screen.queryByLabelText("Client secret")).not.toBeInTheDocument();
  expect(screen.getByText("A client secret is configured.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Issuer URL")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Replace client secret" }));
  expect(screen.getByLabelText("New client secret")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Provider"), {
    target: { value: "generic_oidc" },
  });
  expect(await screen.findByLabelText("Issuer URL")).toBeInTheDocument();
  expect(screen.queryByLabelText("Authorization endpoint")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Token endpoint")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("JWKS URI")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Directory (tenant) ID")).not.toBeInTheDocument();
  expect(screen.getByText(/current configuration remains active until then/i))
    .toBeInTheDocument();
});
