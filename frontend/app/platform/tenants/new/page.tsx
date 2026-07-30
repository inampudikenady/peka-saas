"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Check, Copy } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { InvitationActions } from "@/components/invitation-preview";
import { PlatformShell } from "@/components/platform-shell";
import { TimezoneSelector, browserTimezone } from "@/components/timezone-selector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { platformApi } from "@/lib/api";
import type { TenantCreateResponse } from "@/lib/types";

const schema = z.object({
  slug: z.string().min(2).max(100).regex(
    /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
    "Use lowercase letters, numbers, and hyphens",
  ),
  display_name: z.string().min(2),
  timezone: z.string().min(1),
  initial_admin_email: z.string().email(),
  initial_admin_full_name: z.string().min(2),
});
type Values = z.infer<typeof schema>;

export default function NewTenantPage() {
  const [result, setResult] = useState<TenantCreateResponse | null>(null);
  const [createdValues, setCreatedValues] = useState<Values | null>(null);
  const [error, setError] = useState("");
  const {
    register,
    setValue,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { timezone: "UTC" },
  });
  useEffect(() => {
    setValue("timezone", browserTimezone(), { shouldValidate: true });
  }, [setValue]);
  const submit = async (values: Values) => {
    setError("");
    try {
      const created = await platformApi.createTenant(values);
      setCreatedValues(values);
      setResult(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create tenant.");
    }
  };
  if (result && createdValues) {
    const tenantUrl = result.tenant.tenant_url ?? `/t/${result.tenant.slug}`;
    return (
      <PlatformShell title="Tenant created">
        <Card className="mx-auto max-w-3xl">
          <CardHeader>
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><Check /></div>
            <h2 className="text-2xl font-semibold">{result.tenant.display_name} is ready</h2>
            <p className="mt-1 text-sm text-slate-500">Initial administrator: {createdValues.initial_admin_email}</p>
          </CardHeader>
          <CardContent className="space-y-5">
            <Alert tone="warning">The setup link expires in 24 hours and can only be used once. PEKA cannot display it again after leaving this page.</Alert>
            {[["Tenant URL", tenantUrl], ["One-time administrator setup link", result.admin_setup_link]].map(([label, value]) => (
              <div key={label}>
                <p className="mb-1 text-sm font-medium">{label}</p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <code className="min-w-0 flex-1 overflow-x-auto rounded-md bg-slate-100 p-3 text-xs">{value}</code>
                  <CopyValueButton value={value} />
                  {label === "Tenant URL" && <Button asChild variant="outline"><a href={value} target="_blank" rel="noreferrer">Open</a></Button>}
                </div>
              </div>
            ))}
            <InvitationActions
              email={createdValues.initial_admin_email}
              fullName={createdValues.initial_admin_full_name}
              displayName={result.tenant.display_name}
              tenantUrl={tenantUrl}
              setupLink={result.admin_setup_link}
            />
            <Button asChild variant="outline"><Link href={`/platform/tenants/${result.tenant.slug}`}>Go to tenant details</Link></Button>
          </CardContent>
        </Card>
      </PlatformShell>
    );
  }
  return (
    <PlatformShell title="Create tenant">
      <Card className="mx-auto max-w-3xl">
        <CardHeader><h2 className="text-xl font-semibold">Tenant details</h2><p className="text-sm text-slate-500">Provision an organization and its bootstrap administrator.</p></CardHeader>
        <CardContent>
          <form className="grid gap-5 sm:grid-cols-2" onSubmit={handleSubmit(submit)}>
            {error && <div className="sm:col-span-2"><Alert>{error}</Alert></div>}
            <FormField label="Slug" htmlFor="slug" error={errors.slug?.message} hint="Permanent tenant identifier used in URLs">
              <Input id="slug" {...register("slug")} />
            </FormField>
            <FormField label="Display name" htmlFor="display_name" error={errors.display_name?.message}>
              <Input id="display_name" {...register("display_name")} />
            </FormField>
            <FormField label="Timezone" htmlFor="timezone" error={errors.timezone?.message} hint="Search by city or IANA timezone ID.">
              <TimezoneSelector id="timezone" {...register("timezone")} />
            </FormField>
            <div />
            <FormField label="Initial admin email" htmlFor="initial_admin_email" error={errors.initial_admin_email?.message}>
              <Input id="initial_admin_email" type="email" {...register("initial_admin_email")} />
            </FormField>
            <FormField label="Initial admin full name" htmlFor="initial_admin_full_name" error={errors.initial_admin_full_name?.message}>
              <Input id="initial_admin_full_name" {...register("initial_admin_full_name")} />
            </FormField>
            <div className="sm:col-span-2"><Button disabled={isSubmitting}>{isSubmitting ? "Creating tenant…" : "Create tenant"}</Button></div>
          </form>
        </CardContent>
      </Card>
    </PlatformShell>
  );
}

function CopyValueButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return <Button type="button" variant="outline" onClick={async () => {
    await navigator.clipboard.writeText(value);
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  }}>{done ? <Check className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}{done ? "Copied" : "Copy"}</Button>;
}
