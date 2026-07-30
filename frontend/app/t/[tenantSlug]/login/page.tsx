"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { tenantApi } from "@/lib/api";
import type { TenantSSOLoginOptions } from "@/lib/types";

const schema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

export default function TenantLoginPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  const [error, setError] = useState("");
  const [sso, setSSO] = useState<TenantSSOLoginOptions | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  useEffect(() => {
    void tenantApi.ssoOptions(tenantSlug).then(setSSO).catch(() => {
      setSSO({ provider: null, enabled: false });
    });
  }, [tenantSlug]);

  const submit = async (values: Values) => {
    setError("");
    try {
      await tenantApi.localLogin(tenantSlug, values);
      router.replace(`/t/${tenantSlug}/ai`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed.");
    }
  };
  const ssoLabel = (
    sso?.provider === "microsoft_entra"
      ? "Sign in with Microsoft"
      : "Continue with OpenID Connect"
  );

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">
            {tenantSlug}
          </p>
          <h1 className="mt-2 text-2xl font-semibold">Sign in to PEKA</h1>
          <p className="mt-2 text-sm text-slate-500">
            Use organization SSO or the local break-glass administrator account.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          <form className="space-y-4" onSubmit={handleSubmit(submit)}>
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
              {isSubmitting ? "Signing in…" : "Sign in with password"}
            </Button>
            <div className="text-right">
              <Link
                className="text-sm text-blue-600 hover:underline"
                href={`/t/${tenantSlug}/forgot-password`}
              >
                Forgot password?
              </Link>
            </div>
          </form>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span className="h-px flex-1 bg-slate-200" />OR
            <span className="h-px flex-1 bg-slate-200" />
          </div>
          {sso?.enabled ? (
            <Button variant="outline" className="w-full" asChild>
              <a href={`/t/${encodeURIComponent(tenantSlug)}/api/v1/tenant/auth/login`}>
                <KeyRound className="mr-2 h-4 w-4" />
                {ssoLabel}
              </a>
            </Button>
          ) : (
            <Button variant="outline" className="w-full" disabled>
              <KeyRound className="mr-2 h-4 w-4" />
              {sso === null ? "Loading SSO…" : "SSO is not configured"}
            </Button>
          )}
          <p className="text-center text-xs text-slate-500">
            Local authentication is for emergency and administrative access.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
