"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/alert";
import { ConnectorDetail } from "@/components/connector-detail";
import { PlatformShell } from "@/components/platform-shell";
import { platformApi } from "@/lib/api";
import type { ConnectorDetail as Detail } from "@/lib/types";
export default function Page(){const {connectorId}=useParams<{connectorId:string}>();const [item,setItem]=useState<Detail|null>(null);const [error,setError]=useState("");useEffect(()=>{void platformApi.connector(connectorId).then(setItem).catch(e=>setError(e.message));},[connectorId]);return <PlatformShell title="Connector details"><h1 className="mb-6 text-2xl font-semibold">{item?.name??"Connector details"}</h1>{error&&<Alert>{error}</Alert>}{item?<ConnectorDetail connector={item}/>:!error&&<p>Loading…</p>}</PlatformShell>}
