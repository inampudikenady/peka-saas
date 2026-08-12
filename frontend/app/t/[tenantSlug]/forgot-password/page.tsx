"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useState } from "react";
import { Alert } from "@/components/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { tenantApi } from "@/lib/api";

export default function ForgotPasswordPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setWorking(true);
    try {
      const response = await tenantApi.forgotPassword(tenantSlug, { email });
      setMessage(response.message);
    } catch {
      setMessage("If an active local account matches that email, a password reset link has been sent.");
    } finally {
      setWorking(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
    <Card className="w-full max-w-md">
      <CardHeader><p className="text-sm font-semibold uppercase tracking-wide text-blue-600">{tenantSlug}</p><h1 className="mt-2 text-2xl font-semibold">Forgot password</h1><p className="mt-2 text-sm text-slate-500">Local accounts can request a secure, single-use reset link. SSO passwords remain managed by your identity provider.</p></CardHeader>
      <CardContent className="space-y-4">
        {message ? <Alert tone="success">{message}</Alert> : <form className="space-y-4" onSubmit={submit}><label className="block space-y-1 text-sm"><span className="font-medium">Email</span><Input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><Button className="w-full" disabled={working}>{working ? "Sending…" : "Send password reset link"}</Button></form>}
        <div className="text-center"><Link className="text-sm text-blue-600 hover:underline" href={`/t/${tenantSlug}/login`}>Return to sign in</Link></div>
      </CardContent>
    </Card>
  </main>;
}
