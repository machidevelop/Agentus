"use client";

import Link from "next/link";

import { Cpu, LogOut } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { UserButton, useUser } from "@clerk/nextjs";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { APP_CONFIG } from "@/config/app-config";
import { sidebarItems } from "@/navigation/sidebar/sidebar-items";
import { usePreferencesStore } from "@/stores/preferences/preferences-provider";

import { NavMain } from "./nav-main";

function UserName() {
  const { user, isLoaded } = useUser();
  if (!isLoaded || !user) {
    return (
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate text-muted-foreground">Not signed in</p>
      </div>
    );
  }
  return (
    <div className="flex-1 min-w-0">
      <p className="text-xs font-medium truncate">{user.firstName || user.primaryEmailAddress?.emailAddress || "User"}</p>
      <p className="text-[10px] text-muted-foreground truncate">{user.primaryEmailAddress?.emailAddress || ""}</p>
    </div>
  );
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { sidebarVariant, sidebarCollapsible, isSynced } = usePreferencesStore(
    useShallow((s) => ({
      sidebarVariant: s.values.sidebar_variant,
      sidebarCollapsible: s.values.sidebar_collapsible,
      isSynced: s.isSynced,
    })),
  );

  const variant = isSynced ? sidebarVariant : props.variant;
  const collapsible = isSynced ? sidebarCollapsible : props.collapsible;

  return (
    <Sidebar {...props} variant={variant} collapsible={collapsible}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild>
              <Link prefetch={false} href="/dashboard/overview">
                <Cpu />
                <span className="font-semibold text-base">{APP_CONFIG.name}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={sidebarItems} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="flex items-center gap-2.5 px-2 py-1.5">
              <UserButton
                appearance={{
                  elements: {
                    avatarBox: "size-7",
                  },
                }}
              />
              <UserName />
              <a
                href="/"
                className="ml-auto shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                title="Leave dashboard"
              >
                <LogOut className="size-4" />
              </a>
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
