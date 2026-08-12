"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { PlatformShell } from "@/components/platform-shell";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { platformApi } from "@/lib/api";
import type { DevelopmentEmail } from "@/lib/types";

export default function DevelopmentEmailOutboxPage() {
  const [messages, setMessages] = useState<DevelopmentEmail[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;
    void platformApi.developmentEmailOutbox().then(setMessages).catch((caught) => setError(caught.message));
  }, []);
  if (process.env.NODE_ENV !== "development") {
    return <PlatformShell title="Development Email Outbox" adminOnly><Alert>This development-only page is disabled in this environment.</Alert></PlatformShell>;
  }
  return <PlatformShell title="Development Email Outbox" adminOnly>
    <p className="mb-5 text-sm text-slate-500">Messages are captured locally and are never sent. This page is available only to Platform Administrators in development.</p>
    {error && <Alert>{error}</Alert>}
    {messages?.length === 0 && <p className="rounded border border-dashed p-8 text-center text-sm text-slate-500">No development messages have been captured.</p>}
    <div className="space-y-4">{messages?.map((message) => <Card key={message.id}><CardHeader><div className="flex flex-wrap justify-between gap-2"><div><h2 className="font-semibold">{message.subject}</h2><p className="text-sm text-slate-500">To {message.recipient} · Tenant {message.tenant_name} ({message.tenant_slug})</p></div><div className="text-right text-xs text-slate-500"><div className="capitalize">{message.delivery_state}</div><time>{new Date(message.created_at).toLocaleString()}</time></div></div></CardHeader><CardContent className="space-y-3"><pre className="whitespace-pre-wrap rounded bg-slate-50 p-4 text-sm">{message.body_text}</pre><a className="inline-block break-all text-sm text-blue-600 hover:underline" href={message.action_url}>Open reset link</a></CardContent></Card>)}</div>
    {!messages && !error && <p className="text-sm text-slate-500">Loading captured messages…</p>}
  </PlatformShell>;
}
