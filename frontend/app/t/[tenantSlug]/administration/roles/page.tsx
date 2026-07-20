"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function TenantRolesRedirect() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  useEffect(() => { router.replace(`/t/${tenantSlug}/administration/users`); }, [router, tenantSlug]);
  return <main className="p-8 text-sm text-slate-500">Redirecting to User Management…</main>;
}
