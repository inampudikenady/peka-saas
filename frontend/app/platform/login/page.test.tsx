import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlatformLogin from "@/app/platform/login/page";
import { ApiError, platformApi } from "@/lib/api";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

describe("Platform login recovery guidance", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("shows administrator recovery guidance for a generic authentication failure", async () => {
    vi.spyOn(platformApi, "login").mockRejectedValue(
      new ApiError(401, "Invalid username or password."),
    );
    render(<PlatformLogin />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(
        screen.getByText(
          "Too many unsuccessful sign-in attempts? If you have forgotten your password, contact your PEKA administrator.",
        ),
      ).toBeInTheDocument(),
    );
  });
});
