"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
export default function Page(){const {tenantSlug}=useParams<{tenantSlug:string}>();const router=useRouter();useEffect(()=>router.replace(`/t/${tenantSlug}/connectors`),[router,tenantSlug]);return <main className="p-8 text-sm text-slate-500">Redirecting to connector management…</main>}
