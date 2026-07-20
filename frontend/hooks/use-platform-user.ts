"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, platformApi } from "@/lib/api";
import type { PlatformUser } from "@/lib/types";
export function usePlatformUser() { const router = useRouter(); const [user, setUser] = useState<PlatformUser | null>(null); const [error, setError] = useState(""); useEffect(() => { platformApi.me().then(setUser).catch(e => { if (e instanceof ApiError && e.status === 401) router.replace("/platform/login"); else setError(e instanceof Error ? e.message : "Identity could not be loaded."); }); }, [router]); return { user, error }; }
