"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { platformApi } from "@/lib/api";

const schema = z.object({ new_password: z.string().min(12), confirm: z.string() }).refine(value => value.new_password === value.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Values = z.infer<typeof schema>;

function ResetPasswordForm() {
  const token = useSearchParams().get("token"); const router = useRouter(); const [error, setError] = useState(""); const [success, setSuccess] = useState(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });
  return <main className="flex min-h-screen items-center justify-center p-4"><Card className="w-full max-w-md"><CardHeader><h1 className="text-2xl font-semibold">Set platform password</h1><p className="text-sm text-slate-500">One-time setup and reset links expire after 24 hours.</p></CardHeader><CardContent>{!token ? <Alert>This password setup link is missing its token.</Alert> : success ? <Alert tone="success">Password saved. Redirecting to sign in…</Alert> : <form className="space-y-4" onSubmit={handleSubmit(async values => { setError(""); try { await platformApi.resetPassword({ token, new_password: values.new_password }); setSuccess(true); setTimeout(() => router.replace("/platform/login"), 1000); } catch (e) { setError(e instanceof Error ? e.message : "This link is invalid, expired, or already used."); } })}>{error && <Alert>{error}</Alert>}<FormField label="New password" htmlFor="new_password" error={errors.new_password?.message}><Input id="new_password" type="password" autoComplete="new-password" {...register("new_password")}/></FormField><FormField label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}><Input id="confirm" type="password" autoComplete="new-password" {...register("confirm")}/></FormField><Button className="w-full" disabled={isSubmitting}>Save password</Button></form>}</CardContent></Card></main>;
}

export default function ResetPasswordPage() {
  return <Suspense fallback={<main className="p-8 text-sm text-slate-500">Loading password setup…</main>}><ResetPasswordForm/></Suspense>;
}
