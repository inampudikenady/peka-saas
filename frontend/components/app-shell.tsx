"use client";

import Link from "next/link";
import {
  Bot,
  Building2,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  Menu,
  Plug,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ProfileMenu } from "@/components/profile-menu";
import { cn } from "@/lib/utils";

export type NavItem = {
  label: string;
  href?: string;
  disabled?: boolean;
};

export type SidebarControls = {
  closeMobile: () => void;
};

type SidebarSlot = (controls: SidebarControls) => ReactNode;

type AppShellProps = {
  title: string;
  subtitle: string;
  items: NavItem[];
  children: ReactNode;
  userLabel: string;
  onLogout: () => void;
  profileHref: string;
  passwordManaged?: boolean;
  collapsibleSidebar?: boolean;
  sidebarPreferenceKey?: string;
  navigationContextKey?: string;
  sidebarTop?: SidebarSlot;
  collapsedSidebarTop?: SidebarSlot;
  sidebarContent?: SidebarSlot;
};

const navIcons: Record<string, typeof Bot> = {
  Assistant: Bot,
  Connectors: Plug,
  Administration: Settings,
  Overview: LayoutDashboard,
  Tenants: Building2,
};

function SidebarTooltip({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  return (
    <span
      id={id}
      role="tooltip"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-xs text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
    >
      {children}
    </span>
  );
}

export function AppShell({
  title,
  subtitle,
  items,
  children,
  userLabel,
  onLogout,
  profileHref,
  passwordManaged,
  collapsibleSidebar = false,
  sidebarPreferenceKey,
  navigationContextKey,
  sidebarTop,
  collapsedSidebarTop,
  sidebarContent,
}: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const controls = { closeMobile: () => setMobileOpen(false) };
  const hasExtendedSidebar = Boolean(sidebarTop || sidebarContent);

  useEffect(() => {
    if (!collapsibleSidebar || !sidebarPreferenceKey) return;
    setCollapsed(
      typeof localStorage !== "undefined" &&
        localStorage.getItem(sidebarPreferenceKey) === "true",
    );
  }, [collapsibleSidebar, sidebarPreferenceKey]);

  useEffect(() => {
    setMobileOpen(false);
  }, [navigationContextKey]);

  const active = (href: string) =>
    pathname === href ||
    (href === "/platform/tenants"
      ? pathname.startsWith("/platform/tenants/")
      : pathname.startsWith(`${href}/`));

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    if (sidebarPreferenceKey && typeof localStorage !== "undefined") {
      localStorage.setItem(sidebarPreferenceKey, String(next));
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <aside
        aria-label="Primary navigation"
        data-collapsed={collapsed}
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex flex-col bg-slate-950 text-white transition-[width,transform] duration-200 md:translate-x-0",
          hasExtendedSidebar ? "w-72" : "w-64",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          collapsed
            ? "md:w-[4.5rem]"
            : hasExtendedSidebar
              ? "md:w-72"
              : "md:w-64",
        )}
      >
        <div
          className={cn(
            "flex h-16 shrink-0 items-center justify-between px-5",
            collapsed && "md:justify-center md:px-3",
          )}
        >
          <div className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="shrink-0 text-blue-400" />
            <span className={cn(collapsed && "md:sr-only")}>PEKA</span>
          </div>
          <button
            type="button"
            aria-label="Close navigation"
            className="rounded p-1 text-slate-300 hover:bg-slate-800 md:hidden"
            onClick={controls.closeMobile}
          >
            <X />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {sidebarTop && (
            <div className={cn("mb-3", collapsed && "md:hidden")}>
              {sidebarTop(controls)}
            </div>
          )}
          {collapsed && collapsedSidebarTop && (
            <div className="mb-3 hidden md:block">
              {collapsedSidebarTop(controls)}
            </div>
          )}

          <nav className="space-y-1">
            {items.map((item) => {
              if (item.disabled || !item.href) {
                return (
                  <div
                    key={item.label}
                    className={cn(
                      "px-3 py-2 text-sm text-slate-500",
                      collapsed && "md:text-center md:text-xs",
                    )}
                  >
                    {item.label}
                  </div>
                );
              }
              const Icon = navIcons[item.label] ?? LayoutDashboard;
              const tooltipId = `nav-tooltip-${item.label.replaceAll(" ", "-").toLowerCase()}`;
              return (
                <Link
                  aria-current={active(item.href) ? "page" : undefined}
                  aria-describedby={collapsed ? tooltipId : undefined}
                  key={item.href}
                  href={item.href}
                  onClick={controls.closeMobile}
                  className={cn(
                    "group relative flex items-center gap-3 rounded px-3 py-2 text-sm text-slate-300 hover:bg-slate-800",
                    active(item.href) && "bg-slate-800 text-white",
                    collapsed && "md:justify-center md:px-2",
                  )}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <span className={cn(collapsed && "md:sr-only")}>{item.label}</span>
                  {collapsed && <SidebarTooltip id={tooltipId}>{item.label}</SidebarTooltip>}
                </Link>
              );
            })}
          </nav>

          {sidebarContent && (
            <div className={cn("mt-4", collapsed && "md:hidden")}>
              {sidebarContent(controls)}
            </div>
          )}
        </div>

        {collapsibleSidebar && (
          <div className="hidden shrink-0 border-t border-slate-800 p-3 md:block">
            <button
              type="button"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-describedby={collapsed ? "sidebar-expand-tooltip" : undefined}
              className={cn(
                "group relative flex w-full items-center gap-3 rounded px-3 py-2 text-sm text-slate-300 hover:bg-slate-800",
                collapsed && "justify-center px-2",
              )}
              onClick={toggleCollapsed}
            >
              {collapsed ? (
                <ChevronRight className="h-5 w-5" />
              ) : (
                <>
                  <ChevronLeft className="h-5 w-5" />
                  <span>Collapse sidebar</span>
                </>
              )}
              {collapsed && (
                <SidebarTooltip id="sidebar-expand-tooltip">Expand sidebar</SidebarTooltip>
              )}
            </button>
          </div>
        )}
      </aside>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation drawer"
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={controls.closeMobile}
        />
      )}

      <div
        className={cn(
          "transition-[padding] duration-200",
          collapsed
            ? "md:pl-[4.5rem]"
            : hasExtendedSidebar
              ? "md:pl-72"
              : "md:pl-64",
        )}
      >
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b bg-white px-4 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Open navigation drawer"
              className="rounded p-1 hover:bg-slate-100 md:hidden"
              onClick={() => setMobileOpen(true)}
            >
              <Menu />
            </button>
            <div className="min-w-0">
              <h1 className="truncate font-semibold">{title}</h1>
              <p className="truncate text-xs text-slate-500">{subtitle}</p>
            </div>
          </div>
          <ProfileMenu
            label={userLabel}
            profileHref={profileHref}
            passwordManaged={passwordManaged}
            onLogout={onLogout}
          />
        </header>
        <div className="p-4 sm:p-6 lg:p-8">{children}</div>
      </div>
    </div>
  );
}
