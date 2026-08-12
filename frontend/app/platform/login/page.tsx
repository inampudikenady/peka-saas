"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, platformApi, platformSession } from "@/lib/api";

const schema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

const SIGN_IN_RECOVERY_MESSAGE =
  "Too many unsuccessful sign-in attempts? If you have forgotten your password, contact your PEKA administrator.";

export default function PlatformLogin() {
  const router = useRouter();
  const [error, setError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const submit = async (values: Values) => {
    setError("");
    try {
      const result = await platformApi.login(values);
      platformSession.set(result.access_token);
      const user = await platformApi.me();
      router.replace(
        user.role === "platform_admin" ? "/platform/tenants" : "/platform/overview",
      );
    } catch (caught) {
      platformSession.clear();
      setError(
        caught instanceof ApiError && caught.status === 401
          ? SIGN_IN_RECOVERY_MESSAGE
          : caught instanceof Error
            ? caught.message
            : "Login failed.",
      );
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <p className="mb-2 text-sm font-semibold uppercase tracking-widest text-blue-600">
            PEKA Platform
          </p>
          <h1 className="text-2xl font-semibold">Platform sign in</h1>
          <p className="mt-2 text-sm text-slate-500">
            Access PEKA tenant visibility and platform operations.
          </p>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={handleSubmit(submit)}>
            {error && <Alert>{error}</Alert>}
            <FormField label="Username" htmlFor="username" error={errors.username?.message}>
              <Input id="username" autoComplete="username" {...register("username")} />
            </FormField>
            <FormField label="Password" htmlFor="password" error={errors.password?.message}>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register("password")}
              />
            </FormField>
            <Button className="w-full" disabled={isSubmitting}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
