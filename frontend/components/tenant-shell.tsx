"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AppShell,
  type SidebarControls,
} from "@/components/app-shell";
import { tenantApi } from "@/lib/api";
import type { TenantMe } from "@/lib/types";

type SidebarSlot = (controls: SidebarControls) => React.ReactNode;

type TenantShellProps = {
  slug: string;
  user: TenantMe;
  children: React.ReactNode;
  title: string;
  adminOnly?: boolean;
  aiSidebarTop?: SidebarSlot;
  aiCollapsedSidebarTop?: SidebarSlot;
  aiSidebarContent?: SidebarSlot;
};

export function TenantShell({
  slug,
  user,
  children,
  title,
  adminOnly = false,
  aiSidebarTop,
  aiCollapsedSidebarTop,
  aiSidebarContent,
}: TenantShellProps) {
  const router = useRouter();
  const admin = user.role === "tenant_admin";

  if (adminOnly && !admin) {
    return (
      <main className="mx-auto max-w-xl p-10">
        <h1 className="text-2xl font-semibold">Access forbidden</h1>
        <p className="mt-2 text-sm text-slate-500">
          Tenant administrator access is required.
        </p>
        <Link
          className="mt-4 inline-block text-blue-600 hover:underline"
          href={`/t/${slug}/ai`}
        >
          Go to Assistant
        </Link>
      </main>
    );
  }

  const items = admin
    ? [
        { label: "Assistant", href: `/t/${slug}/ai` },
        { label: "Connectors", href: `/t/${slug}/connectors` },
        { label: "Administration", href: `/t/${slug}/administration` },
      ]
    : [];

  const hasAIHistory = Boolean(aiSidebarTop || aiSidebarContent);

  return (
    <AppShell
      title={title}
      subtitle={`${user.tenant_name} · ${
        admin ? "Tenant administrator" : "Tenant user"
      }`}
      userLabel={user.full_name}
      profileHref={`/t/${slug}/profile`}
      passwordManaged={user.auth_source === "sso"}
      items={items}
      collapsibleSidebar={hasAIHistory}
      sidebarPreferenceKey={hasAIHistory ? "peka:tenant-ai-sidebar-collapsed" : undefined}
      navigationContextKey={slug}
      sidebarTop={aiSidebarTop}
      collapsedSidebarTop={aiCollapsedSidebarTop}
      sidebarContent={aiSidebarContent}
      onLogout={async () => {
        try {
          await tenantApi.logout(slug);
        } finally {
          router.replace(`/t/${slug}/login`);
        }
      }}
    >
      {children}
    </AppShell>
  );
}
