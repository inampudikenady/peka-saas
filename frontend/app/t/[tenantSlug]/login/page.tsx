"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { tenantApi } from "@/lib/api";
const schema = z.object({ username: z.string().min(1, "Username is required"), password: z.string().min(1, "Password is required") });
type Values = z.infer<typeof schema>;
export default function TenantLoginPage() { const { tenantSlug } = useParams<{ tenantSlug: string }>(); const router = useRouter(); const [error, setError] = useState(""); const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) }); const submit = async (values: Values) => { setError(""); try { await tenantApi.localLogin(tenantSlug, values); router.replace(`/t/${tenantSlug}/ai`); } catch (e) { setError(e instanceof Error ? e.message : "Login failed."); } }; return <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4"><Card className="w-full max-w-md"><CardHeader><p className="text-sm font-semibold uppercase tracking-wide text-blue-600">{tenantSlug}</p><h1 className="mt-2 text-2xl font-semibold">Sign in to PEKA</h1><p className="mt-2 text-sm text-slate-500">Use organization SSO or the local break-glass administrator account.</p></CardHeader><CardContent className="space-y-5"><form className="space-y-4" onSubmit={handleSubmit(submit)}>{error && <Alert>{error}</Alert>}<FormField label="Username" htmlFor="username" error={errors.username?.message}><Input id="username" autoComplete="username" {...register("username")}/></FormField><FormField label="Password" htmlFor="password" error={errors.password?.message}><Input id="password" type="password" autoComplete="current-password" {...register("password")}/></FormField><Button className="w-full" disabled={isSubmitting}>{isSubmitting ? "Signing in…" : "Sign in with password"}</Button></form><div className="flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200"/>OR<span className="h-px flex-1 bg-slate-200"/></div><Button variant="outline" className="w-full" asChild><a href={`/t/${encodeURIComponent(tenantSlug)}/api/v1/tenant/auth/login`}><KeyRound className="mr-2 h-4 w-4"/>Continue with SSO</a></Button><p className="text-center text-xs text-slate-500">Local authentication is for emergency and administrative access. No tenant username is assumed by this page.</p><div className="text-center"><Link className="text-sm text-blue-600 hover:underline" href={`/t/${tenantSlug}`}>Back to tenant home</Link></div></CardContent></Card></main>; }
