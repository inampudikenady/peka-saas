"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConnectorTable } from "@/components/connector-table";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { ManagedConnector } from "@/lib/types";

export default function ConnectorsPage(){
  const {tenantSlug}=useParams<{tenantSlug:string}>(); const {user,error:userError}=useTenantUser(tenantSlug); const [items,setItems]=useState<ManagedConnector[]|null>(null); const [error,setError]=useState("");
  useEffect(()=>{void tenantApi.connectors(tenantSlug).then(setItems).catch(e=>setError(e.message));},[tenantSlug]);
  if(!user)return <main className="p-8">{userError||"Loading…"}</main>;
  const retire=async(connector:ManagedConnector)=>{if(!window.confirm(`Retire ${connector.name}? It will no longer be able to authenticate.`))return;try{const next=await tenantApi.retireConnector(tenantSlug,connector.id);setItems(current=>current?.map(item=>item.id===next.id?next:item)??[]);}catch(e){setError(e instanceof Error?e.message:"Retirement failed.");}};
  return <TenantShell slug={tenantSlug} user={user} title="Connectors"><div className="mb-6 flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-2xl font-semibold">Connectors</h2><p className="text-sm text-slate-500">Customer appliance communication and local source health.</p><p className="mt-1 text-xs text-slate-500">Connected means the connector is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized.</p></div><Button asChild><Link href={`/t/${tenantSlug}/connectors/registration-tokens`}>Registration tokens</Link></Button></div>{error&&<Alert>{error}</Alert>}{items?<ConnectorTable connectors={items} detailBase={`/t/${tenantSlug}/connectors`} canRetire={user.role==="tenant_admin"} onRetire={retire}/>:<p className="text-sm text-slate-500">Loading connectors…</p>}</TenantShell>;
}
