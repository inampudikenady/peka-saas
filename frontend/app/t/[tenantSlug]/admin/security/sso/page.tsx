"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { FormField } from "@/components/form-field";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { ApiError, tenantApi } from "@/lib/api";
import type { TenantSSOConfig } from "@/lib/types";

const schema = z.object({
  provider: z.enum(["microsoft_entra", "generic_oidc"]),
  entra_tenant_id: z.string().optional(),
  issuer_url: z.string().optional(),
  client_id: z.string().trim().min(1, "Client ID is required"),
  client_secret: z.string().max(1000).optional(),
  enabled: z.boolean(),
}).superRefine((values, context) => {
  if (values.provider === "microsoft_entra") {
    const tenantId = values.entra_tenant_id ?? "";
    if (tenantId !== tenantId.trim() || !z.string().uuid().safeParse(tenantId).success) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["entra_tenant_id"],
        message: "Enter a valid Directory (tenant) UUID without whitespace",
      });
    }
  } else {
    const issuer = values.issuer_url ?? "";
    let validIssuer = false;
    try {
      const parsed = new URL(issuer);
      validIssuer = (
        issuer === issuer.trim()
        && parsed.protocol === "https:"
        && !parsed.username
        && !parsed.password
        && !parsed.search
        && !parsed.hash
      );
    } catch {}
    if (!validIssuer) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["issuer_url"],
        message: "Enter a valid HTTPS issuer URL without a query or fragment",
      });
    }
  }
});

type Values = z.infer<typeof schema>;

const emptyValues: Values = {
  provider: "microsoft_entra",
  entra_tenant_id: "",
  issuer_url: "",
  client_id: "",
  client_secret: "",
  enabled: false,
};

export default function SSOSettingsPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  const { user, error: userError } = useTenantUser(tenantSlug);
  const [config, setConfig] = useState<TenantSSOConfig | null>(null);
  const [apiError, setApiError] = useState("");
  const [success, setSuccess] = useState("");
  const [isTesting, setIsTesting] = useState(false);
  const [replaceSecret, setReplaceSecret] = useState(false);
  const {
    register,
    reset,
    handleSubmit,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: emptyValues,
  });

  useEffect(() => {
    tenantApi.getSSO(tenantSlug).then((value) => {
      setConfig(value);
      setReplaceSecret(!value.client_secret_configured);
      reset({
        provider: value.provider,
        entra_tenant_id: value.entra_tenant_id ?? "",
        issuer_url: value.issuer_url ?? "",
        client_id: value.client_id ?? "",
        client_secret: "",
        enabled: value.enabled,
      });
    }).catch((caught) => {
      if (caught instanceof ApiError && caught.status === 401) {
        router.replace(`/t/${tenantSlug}/login`);
      } else {
        setApiError(
          caught instanceof Error ? caught.message : "Could not load SSO settings.",
        );
      }
    });
  }, [reset, router, tenantSlug]);

  const provider = watch("provider");
  const enabled = watch("enabled");
  const providerChanged = Boolean(config && provider !== config.provider);

  const submit = async (values: Values) => {
    setApiError("");
    setSuccess("");
    if (!config?.client_secret_configured && !values.client_secret) {
      setError("client_secret", {
        message: "Client secret is required for initial SSO configuration",
      });
      return;
    }
    try {
      const next = await tenantApi.updateSSO(tenantSlug, {
        provider: values.provider,
        entra_tenant_id: (
          values.provider === "microsoft_entra"
            ? values.entra_tenant_id
            : null
        ),
        issuer_url: (
          values.provider === "generic_oidc" ? values.issuer_url : null
        ),
        client_id: values.client_id,
        client_secret: replaceSecret ? values.client_secret || null : null,
        enabled: values.enabled,
      });
      setConfig(next);
      setReplaceSecret(false);
      reset({ ...values, client_secret: "" });
      setSuccess("SSO configuration saved locally. Use Test configuration to verify provider discovery.");
    } catch (caught) {
      const message = (
        caught instanceof Error ? caught.message : "Could not save SSO settings."
      );
      if (/tenant id/i.test(message)) {
        setError("entra_tenant_id", { message });
      } else if (/issuer|discovery/i.test(message)) {
        setError("issuer_url", { message });
      } else if (/client secret/i.test(message)) {
        setError("client_secret", { message });
        setReplaceSecret(true);
      } else if (/client id/i.test(message)) {
        setError("client_id", { message });
      } else {
        setApiError(message);
      }
    }
  };

  const testConfiguration = async () => {
    setApiError("");
    setSuccess("");
    setIsTesting(true);
    try {
      const result = await tenantApi.testSSO(tenantSlug);
      setSuccess(result.message);
    } catch (caught) {
      setApiError(caught instanceof Error ? caught.message : "Could not test SSO configuration.");
    } finally {
      setIsTesting(false);
    }
  };

  if (userError) return <main className="p-8"><Alert>{userError}</Alert></main>;
  if (!user) {
    return <main className="p-8 text-sm text-slate-500">Loading security settings…</main>;
  }

  return (
    <TenantShell slug={tenantSlug} user={user} title="Security · Single Sign-On">
      <Card className="max-w-3xl">
        <CardHeader>
          <h2 className="text-xl font-semibold">Single Sign-On</h2>
          <p className="text-sm text-slate-500">
            Both provider options use PEKA&apos;s standard OpenID Connect flow.
          </p>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={handleSubmit(submit)}>
            {apiError && <Alert>{apiError}</Alert>}
            {success && <Alert tone="success">{success}</Alert>}
            {providerChanged && (
              <Alert tone="warning">
                Changing provider replaces the saved provider-specific configuration
                only when you save. The current configuration remains active until then.
              </Alert>
            )}
            {enabled && (
              <Alert tone="warning">
                Register the exact redirect URI below before enabling SSO. The local
                break-glass administrator remains available.
              </Alert>
            )}
            <FormField label="Provider" htmlFor="provider" error={errors.provider?.message}>
              <select
                id="provider"
                className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
                {...register("provider")}
              >
                <option value="microsoft_entra">Microsoft Entra ID</option>
                <option value="generic_oidc">Generic OpenID Connect</option>
              </select>
            </FormField>

            {provider === "microsoft_entra" ? (
              <FormField
                label="Directory (tenant) ID"
                htmlFor="entra_tenant_id"
                error={errors.entra_tenant_id?.message}
                hint="Use the UUID shown as Directory (tenant) ID in Microsoft Entra."
              >
                <Input
                  id="entra_tenant_id"
                  autoComplete="off"
                  {...register("entra_tenant_id")}
                />
              </FormField>
            ) : (
              <FormField
                label="Issuer URL"
                htmlFor="issuer_url"
                error={errors.issuer_url?.message}
                hint="PEKA loads authorization, token, and signing-key endpoints through OIDC discovery."
              >
                <Input id="issuer_url" {...register("issuer_url")} />
              </FormField>
            )}

            <FormField label="Client ID" htmlFor="client_id" error={errors.client_id?.message}>
              <Input id="client_id" autoComplete="off" {...register("client_id")} />
            </FormField>

            {config?.client_secret_configured && !replaceSecret ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4">
                <p className="text-sm font-medium text-emerald-900">
                  A client secret is configured.
                </p>
                <p className="mt-1 text-xs text-emerald-800">
                  PEKA never displays the stored value. Leave it unchanged or deliberately
                  replace it.
                </p>
                <Button
                  className="mt-3"
                  type="button"
                  variant="outline"
                  onClick={() => setReplaceSecret(true)}
                >
                  Replace client secret
                </Button>
              </div>
            ) : (
              <FormField
                label={config?.client_secret_configured ? "New client secret" : "Client secret"}
                htmlFor="client_secret"
                error={errors.client_secret?.message}
                hint={
                  config?.client_secret_configured
                    ? "Leave blank and cancel replacement to retain the existing secret."
                    : "Required for initial SSO configuration."
                }
              >
                <div className="space-y-2">
                  <Input
                    id="client_secret"
                    type="password"
                    autoComplete="new-password"
                    {...register("client_secret")}
                  />
                  {config?.client_secret_configured && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setReplaceSecret(false)}
                    >
                      Keep existing secret
                    </Button>
                  )}
                </div>
              </FormField>
            )}

            <FormField
              label="Redirect URI"
              htmlFor="redirect_uri"
              hint="Register this exact URI with the identity provider."
            >
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id="redirect_uri"
                  value={config?.redirect_uri ?? "Available after the first successful save"}
                  readOnly
                  disabled
                />
                {config?.redirect_uri && <CopyButton value={config.redirect_uri} />}
              </div>
            </FormField>
            <label className="flex items-start gap-3 rounded-md border border-slate-200 p-4">
              <input type="checkbox" className="mt-1 h-4 w-4" {...register("enabled")} />
              <span>
                <span className="block text-sm font-medium">Enable SSO</span>
                <span className="block text-xs text-slate-500">
                  Users can authenticate through this OpenID Connect provider.
                </span>
              </span>
            </label>
            <div className="flex flex-wrap gap-3">
              <Button disabled={isSubmitting || isTesting}>
                {isSubmitting ? "Saving…" : "Save SSO configuration"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={isSubmitting || isTesting || !config?.client_secret_configured}
                onClick={testConfiguration}
              >
                {isTesting ? "Testing discovery…" : "Test configuration"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </TenantShell>
  );
}
