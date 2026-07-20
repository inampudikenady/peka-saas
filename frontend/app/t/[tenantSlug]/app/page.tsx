"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function TenantDashboardRedirect() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  useEffect(() => { router.replace(`/t/${tenantSlug}/ai`); }, [router, tenantSlug]);
  return <main className="p-8 text-sm text-slate-500">Redirecting to AI Assistant…</main>;
}
