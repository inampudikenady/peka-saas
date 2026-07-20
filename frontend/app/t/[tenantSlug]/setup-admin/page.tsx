"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { tenantApi } from "@/lib/api";
const schema = z.object({ password: z.string().min(12, "Use at least 12 characters"), confirm: z.string() }).refine(v => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Values = z.infer<typeof schema>;
export default function SetupAdminPage() { const { tenantSlug } = useParams<{ tenantSlug: string }>(); const token = useSearchParams().get("token"); const router = useRouter(); const [error, setError] = useState(""); const [success, setSuccess] = useState(false); const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) }); const submit = async ({ password }: Values) => { if (!token) return; setError(""); try { await tenantApi.activate(tenantSlug, { token, password }); setSuccess(true); setTimeout(() => router.replace(`/t/${tenantSlug}/ai`), 900); } catch (e) { const message = e instanceof Error ? e.message : "Account setup failed."; setError(message.includes("expired") || message.includes("used") || message.includes("Invalid") ? `${message} Ask your platform administrator to regenerate the setup invitation.` : message); } }; return <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4"><Card className="w-full max-w-md"><CardHeader><p className="text-sm font-semibold uppercase tracking-wide text-blue-600">Tenant · {tenantSlug}</p><h1 className="mt-2 text-2xl font-semibold">Set up administrator</h1><p className="mt-2 text-sm text-slate-500">Choose a strong password for your local break-glass administrator.</p></CardHeader><CardContent>{success ? <Alert tone="success">Administrator access is ready. Redirecting to your tenant workspace…</Alert> : !token ? <Alert>This setup link is missing its token. Request a new invitation from the platform administrator.</Alert> : <form className="space-y-5" onSubmit={handleSubmit(submit)}>{error && <Alert>{error}</Alert>}<FormField label="Password" htmlFor="password" error={errors.password?.message}><Input id="password" type="password" autoComplete="new-password" {...register("password")}/></FormField><FormField label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}><Input id="confirm" type="password" autoComplete="new-password" {...register("confirm")}/></FormField><Button className="w-full" disabled={isSubmitting}>{isSubmitting ? "Activating…" : "Activate account"}</Button></form>}</CardContent></Card></main>; }
