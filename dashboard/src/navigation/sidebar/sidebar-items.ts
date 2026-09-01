import {
  Activity,
  ClipboardCheck,
  DollarSign,
  LayoutDashboard,
  type LucideIcon,
  Search,
  Server,
  TrendingUp,
  Zap,
} from "lucide-react";

export type NavBadge = "new" | "soon";

export interface NavSubItem {
  id: string;
  title: string;
  url: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

interface NavItemBase {
  id: string;
  title: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

export interface NavMainLinkItem extends NavItemBase {
  url: string;
  subItems?: never;
}

export interface NavMainParentItem extends NavItemBase {
  subItems: NavSubItem[];
}

export type NavMainItem = NavMainLinkItem | NavMainParentItem;

export interface NavGroup {
  id: number;
  label?: string;
  items: NavMainItem[];
}

export const sidebarItems: NavGroup[] = [
  {
    id: 1,
    label: "Intelligence",
    items: [
      {
        id: "overview",
        title: "Overview",
        url: "/dashboard/overview",
        icon: LayoutDashboard,
      },
      {
        id: "findings",
        title: "Findings",
        url: "/dashboard/findings",
        icon: Search,
      },
      {
        id: "cluster",
        title: "Cluster View",
        url: "/dashboard/cluster",
        icon: Server,
      },
      {
        id: "economics",
        title: "Economics",
        url: "/dashboard/economics",
        icon: DollarSign,
      },
      {
        id: "trends",
        title: "Trends",
        url: "/dashboard/trends",
        icon: TrendingUp,
      },
      {
        id: "gpu-health",
        title: "GPU Health",
        url: "/dashboard/gpu-health",
        icon: Activity,
      },
      {
        id: "review",
        title: "Review Queue",
        url: "/dashboard/review",
        icon: ClipboardCheck,
      },
      {
        id: "agents",
        title: "Agents",
        url: "/dashboard/agents",
        icon: Zap,
      },
    ],
  },
];
