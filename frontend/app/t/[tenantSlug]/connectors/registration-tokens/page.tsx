"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { CopyButton } from "@/components/copy-button";
import { StatusBadge } from "@/components/status-badge";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { RegistrationToken, RegistrationTokenCreated } from "@/lib/types";

export default function Page(){
  const {tenantSlug}=useParams<{tenantSlug:string}>();const {user}=useTenantUser(tenantSlug);const [items,setItems]=useState<RegistrationToken[]>([]);const [created,setCreated]=useState<RegistrationTokenCreated|null>(null);const [name,setName]=useState("");const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  const load=useCallback(()=>tenantApi.registrationTokens(tenantSlug).then(setItems).catch(e=>setError(e.message)),[tenantSlug]);useEffect(()=>{void load();},[load]);if(!user)return <main className="p-8">Loading…</main>;
  const generate=async()=>{setBusy(true);setError("");try{const token=await tenantApi.createRegistrationToken(tenantSlug,name.trim()||null);setCreated(token);setItems(current=>[token,...current]);setName("");}catch(e){setError(e instanceof Error?e.message:"Could not generate token.");}finally{setBusy(false);}};
  return <TenantShell slug={tenantSlug} user={user} title="Registration tokens"><div className="mb-6 flex items-end justify-between"><div><h1 className="text-2xl font-semibold">Registration Tokens</h1><p className="text-sm text-slate-500">Single-use credentials expire after 30 minutes. Stored values are hashed.</p></div><Button asChild variant="outline"><Link href={`/t/${tenantSlug}/connectors`}>Back to connectors</Link></Button></div>{error&&<Alert>{error}</Alert>}{created&&<div className="mb-6 rounded-lg border border-amber-300 bg-amber-50 p-5"><h2 className="font-semibold">Copy this token now</h2><p className="mt-1 text-sm text-amber-900">This is the only time PEKA will display the raw registration token.</p><code className="my-4 block overflow-x-auto rounded bg-white p-3 text-xs">{created.registration_token}</code><CopyButton value={created.registration_token}/><Button className="ml-2" variant="ghost" onClick={()=>setCreated(null)}>Dismiss</Button></div>}{user.role==="tenant_admin"&&<Card className="mb-6 p-5"><h2 className="font-semibold">Generate token</h2><div className="mt-3 flex max-w-2xl gap-3"><Input value={name} onChange={e=>setName(e.target.value)} placeholder="Intended connector name (optional)"/><Button disabled={busy} onClick={generate}>{busy?"Generating…":"Generate token"}</Button></div></Card>}<Card className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b bg-slate-50"><tr>{["Created","Intended connector","Expires","Status","Actions"].map(x=><th className="px-4 py-3" key={x}>{x}</th>)}</tr></thead><tbody>{items.map(token=><tr className="border-b" key={token.id}><td className="px-4 py-4">{new Date(token.created_at).toLocaleString()}</td><td className="px-4">{token.intended_connector_name??"Any"}</td><td className="px-4">{new Date(token.expires_at).toLocaleString()}</td><td className="px-4"><StatusBadge status={token.status}/></td><td className="px-4">{user.role==="tenant_admin"&&token.status==="active"?<Button variant="danger" onClick={async()=>{if(!window.confirm("Revoke this unused token?"))return;try{await tenantApi.revokeRegistrationToken(tenantSlug,token.id);await load();}catch(e){setError(e instanceof Error?e.message:"Revocation failed.");}}}>Revoke</Button>:<span className="text-xs text-slate-500">No actions</span>}</td></tr>)}</tbody></table>{!items.length&&<p className="p-5 text-sm text-slate-500">No registration tokens.</p>}</Card></TenantShell>;
}
