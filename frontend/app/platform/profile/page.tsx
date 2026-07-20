"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/alert";
import { FormField } from "@/components/form-field";
import { PlatformShell } from "@/components/platform-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { usePlatformUser } from "@/hooks/use-platform-user";
import { platformApi } from "@/lib/api";
const schema = z.object({ current_password: z.string().min(1), new_password: z.string().min(12), confirm: z.string() }).refine(v => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" }); type Values = z.infer<typeof schema>;
export default function PlatformProfilePage() { const { user } = usePlatformUser(); const [error, setError] = useState(""); const [success, setSuccess] = useState(""); const { register, reset, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) }); return <PlatformShell title="Profile"><div className="grid max-w-4xl gap-6 lg:grid-cols-2"><Card><CardHeader><h2 className="text-lg font-semibold">Your identity</h2></CardHeader><CardContent className="space-y-3">{user && <><p className="font-medium">{user.full_name}</p><p className="text-sm text-slate-500">{user.username} · {user.email}</p><StatusBadge status={user.role === "platform_admin" ? "Platform admin" : "Read only"}/></>}</CardContent></Card><Card><CardHeader><h2 className="text-lg font-semibold">Change password</h2></CardHeader><CardContent><form className="space-y-4" onSubmit={handleSubmit(async values => { setError(""); setSuccess(""); try { await platformApi.changePassword(values); setSuccess("Password changed successfully."); reset(); } catch (e) { setError(e instanceof Error ? e.message : "Password change failed."); } })}>{error && <Alert>{error}</Alert>}{success && <Alert tone="success">{success}</Alert>}<FormField label="Current password" htmlFor="current" error={errors.current_password?.message}><Input id="current" type="password" {...register("current_password")}/></FormField><FormField label="New password" htmlFor="new" error={errors.new_password?.message}><Input id="new" type="password" {...register("new_password")}/></FormField><FormField label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}><Input id="confirm" type="password" {...register("confirm")}/></FormField><Button disabled={isSubmitting}>Change password</Button></form></CardContent></Card></div></PlatformShell>; }
