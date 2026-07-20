"use client";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConnectorTable } from "@/components/connector-table";
import { PlatformShell } from "@/components/platform-shell";
import { platformApi } from "@/lib/api";
import type { ManagedConnector } from "@/lib/types";
export default function Page(){const [items,setItems]=useState<ManagedConnector[]|null>(null);const [error,setError]=useState("");useEffect(()=>{void platformApi.connectors().then(setItems).catch(e=>setError(e.message));},[]);return <PlatformShell title="Connectors"><div className="mb-6"><h1 className="text-2xl font-semibold">Platform Connectors</h1><p className="text-sm text-slate-500">Read-only connector inventory across all tenants.</p><p className="mt-1 text-xs text-slate-500">Connected means the connector is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized.</p></div>{error&&<Alert>{error}</Alert>}{items?<ConnectorTable connectors={items} detailBase="/platform/connectors" platform/>:<p className="text-sm text-slate-500">Loading connectors…</p>}</PlatformShell>}
