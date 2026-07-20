"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, tenantApi } from "@/lib/api";
import type { TenantMe } from "@/lib/types";
export function useTenantUser(slug: string) { const router = useRouter(); const [user, setUser] = useState<TenantMe | null>(null); const [error, setError] = useState(""); useEffect(() => { tenantApi.me(slug).then(setUser).catch(e => { if (e instanceof ApiError && e.status === 401) router.replace(`/t/${slug}/login`); else setError(e instanceof Error ? e.message : "Could not load your session."); }); }, [router, slug]); return { user, error }; }
