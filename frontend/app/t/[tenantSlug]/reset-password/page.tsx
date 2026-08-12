"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";
import { Alert } from "@/components/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { tenantApi } from "@/lib/api";

export default function ResetPasswordPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(token ? "" : "This password reset link is invalid.");
  const [complete, setComplete] = useState(false);
  const [working, setWorking] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (password !== confirm) { setError("Passwords do not match."); return; }
    setWorking(true);
    try {
      await tenantApi.resetPassword(tenantSlug, { token, new_password: password });
      setComplete(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Password reset failed.");
    } finally {
      setWorking(false);
    }
  };
  return <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4"><Card className="w-full max-w-md"><CardHeader><p className="text-sm font-semibold uppercase tracking-wide text-blue-600">{tenantSlug}</p><h1 className="mt-2 text-2xl font-semibold">Reset password</h1><p className="mt-2 text-sm text-slate-500">Choose a password of at least 12 characters.</p></CardHeader><CardContent className="space-y-4">{error && <Alert>{error}</Alert>}{complete ? <Alert tone="success">Your password has been reset and the account unlocked. You can now sign in.</Alert> : <form className="space-y-4" onSubmit={submit}><Input aria-label="New password" type="password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} /><Input aria-label="Confirm password" type="password" minLength={12} required value={confirm} onChange={(event) => setConfirm(event.target.value)} /><Button className="w-full" disabled={working || !token}>{working ? "Resetting…" : "Reset password"}</Button></form>}<div className="text-center"><Link className="text-sm text-blue-600 hover:underline" href={`/t/${tenantSlug}/login`}>Return to sign in</Link></div></CardContent></Card></main>;
}
