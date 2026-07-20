"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { InvitationActions } from "@/components/invitation-preview";
import { PlatformShell } from "@/components/platform-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { platformApi } from "@/lib/api";
import type { PlatformInvitation } from "@/lib/types";
const schema = z.object({ username: z.string().min(2), full_name: z.string().min(2), email: z.string().email(), role: z.enum(["platform_admin", "platform_readonly"]) }); type Values = z.infer<typeof schema>;
export default function NewPlatformUserPage() { const [result, setResult] = useState<PlatformInvitation | null>(null); const [error, setError] = useState(""); const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { role: "platform_readonly" } }); if (result) return <PlatformShell title="Platform user created" adminOnly><Card className="max-w-2xl"><CardHeader><h2 className="text-xl font-semibold">Invite {result.user.full_name}</h2><p className="text-sm text-slate-500">This one-time link expires {new Date(result.expires_at).toLocaleString()}.</p></CardHeader><CardContent><code className="block overflow-x-auto rounded bg-slate-100 p-3 text-xs">{result.setup_link}</code><div className="mt-4"><InvitationActions email={result.user.email} fullName={result.user.full_name} displayName="PEKA Platform" tenantUrl="PEKA Platform Administration" setupLink={result.setup_link}/></div></CardContent></Card></PlatformShell>; return <PlatformShell title="Add platform user" adminOnly><Card className="max-w-2xl"><CardHeader><h2 className="text-xl font-semibold">New platform user</h2></CardHeader><CardContent><form className="space-y-5" onSubmit={handleSubmit(async values => { setError(""); try { setResult(await platformApi.createUser(values)); } catch (e) { setError(e instanceof Error ? e.message : "User creation failed."); } })}>{error && <Alert>{error}</Alert>}<FormField label="Username" htmlFor="username" error={errors.username?.message}><Input id="username" {...register("username")}/></FormField><FormField label="Full name" htmlFor="full_name" error={errors.full_name?.message}><Input id="full_name" {...register("full_name")}/></FormField><FormField label="Email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" {...register("email")}/></FormField><FormField label="Role" htmlFor="role" error={errors.role?.message}><select id="role" className="h-10 w-full rounded border px-3" {...register("role")}><option value="platform_readonly">Read only</option><option value="platform_admin">Administrator</option></select></FormField><Button disabled={isSubmitting}>{isSubmitting ? "Creating…" : "Create and generate setup link"}</Button></form></CardContent></Card></PlatformShell>; }
