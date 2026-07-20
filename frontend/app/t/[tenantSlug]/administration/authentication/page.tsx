"use client";
import { useParams } from "next/navigation";
import SSOSettingsPage from "../../admin/security/sso/page";
import { useTenantUser } from "@/hooks/use-tenant-user";
export default function AuthenticationPage(){const {tenantSlug}=useParams<{tenantSlug:string}>();const {user}=useTenantUser(tenantSlug);if(!user)return <main className="p-8">Loading…</main>;if(user.role!=="tenant_admin")return <main className="p-8"><h1 className="text-2xl font-semibold">Access forbidden</h1></main>;return <SSOSettingsPage/>}
