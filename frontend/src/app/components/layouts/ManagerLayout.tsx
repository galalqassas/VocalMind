import { Fragment, useState } from "react";
import { Outlet, Link, useLocation } from "react-router";
import { UserNav } from "./UserNav";
import {
  LayoutDashboard,
  Search,
  MessageSquare,
  BookOpen,
  ClipboardCheck,
  Download,
  Menu,
} from "lucide-react";
import logoSrc from "../../../assets/logo/logo.svg";
import { Separator } from "../ui/separator";
import { NotificationBell } from "../notifications/NotificationBell";

export function ManagerLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  const navItems = [
    { icon: LayoutDashboard, label: "Dashboard", path: "/manager" },
    { icon: Search, label: "Session Inspector", path: "/manager/inspector" },
    { icon: ClipboardCheck, label: "Review Queue", path: "/manager/reviews" },
    { icon: MessageSquare, label: "Manager Assistant", path: "/manager/assistant" },
    { icon: BookOpen, label: "Knowledge Base", path: "/manager/knowledge" },
  ];

  const getPageTitle = () => {
    if (location.pathname === "/manager") return "Dashboard";
    if (location.pathname.includes("inspector") && !location.pathname.includes("/manager/inspector/")) return "Session Inspector";
    if (location.pathname.includes("inspector/")) return "Call Detail";
    if (location.pathname.includes("reviews")) return "Review Queue";
    if (location.pathname.includes("notifications")) return "Notifications";
    if (location.pathname.includes("assistant")) return "Manager Assistant";
    if (location.pathname.includes("knowledge")) return "Knowledge Base";
    return "Dashboard";
  };

  return (
    <div className="flex flex-col h-screen bg-background text-foreground transition-colors duration-300">
      {/* Global Top Bar */}
      <div className="h-16 bg-card border-b border-border px-6 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-5">
          <button
            onClick={() => setCollapsed(!collapsed)}
            data-cy="sidebar-collapse-toggle"
            className="flex items-center justify-center w-9 h-9 rounded-xl hover:bg-accent text-muted-foreground hover:text-foreground transition-all cursor-pointer"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <Menu className="w-5 h-5" />
          </button>
          <Link to="/manager" className="flex items-center gap-2.5">
            <img src={logoSrc} alt="VocalMind" className="w-[30px] h-[30px] object-contain flex-shrink-0" />
            <span className="text-foreground font-bold text-[17px] tracking-tight" style={{ fontFamily: 'var(--font-sans)' }}>
              VocalMind
            </span>
          </Link>
          <div className="h-4 w-px bg-border/60 mx-1" />
          <div className="flex items-center gap-2.5">
            <h1 className="text-[15px] font-bold text-foreground">
              {getPageTitle()}
            </h1>
            <span className="px-2.5 py-0.5 bg-primary/10 text-primary border border-primary/20 rounded-full text-[10px] font-bold uppercase tracking-wide">
              Manager
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-3 h-8 border border-border rounded-lg text-[13px] text-muted-foreground hover:bg-accent transition-colors">
            <Download className="w-3.5 h-3.5" />
            Export
          </button>
          <NotificationBell />
          <UserNav />
        </div>
      </div>

      {/* Main Split Layout */}
      <div className="flex-1 flex overflow-hidden min-w-0">
        {/* Collapsible Sidebar */}
        <div
          className={`${
            collapsed ? "w-[72px]" : "w-[240px]"
          } bg-sidebar border-r border-sidebar-border flex flex-col transition-all duration-300 flex-shrink-0`}
        >
          <div className="flex-1 flex flex-col justify-between py-4">
            <div>
              <nav className="px-2 flex flex-col gap-0.5" aria-label="Manager navigation">
                {navItems.map((item, index) => {
                  const Icon = item.icon;
                  const isActive =
                    location.pathname === item.path ||
                    (item.path === "/manager/inspector" &&
                      location.pathname.includes("/manager/inspector"));

                  return (
                    <Fragment key={item.path}>
                      {index > 0 && (
                        <Separator className="my-2 bg-sidebar-border/60" decorative />
                      )}
                      <Link
                        to={item.path}
                        className={`flex items-center gap-3 px-3.5 h-11 rounded-xl transition-all ${
                          isActive
                            ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                            : "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                        }`}
                      >
                        <Icon className="w-[18px] h-[18px] flex-shrink-0" />
                        {!collapsed && (
                          <span className="text-[13.5px] font-semibold truncate">{item.label}</span>
                        )}
                      </Link>
                    </Fragment>
                  );
                })}
              </nav>
            </div>
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto min-w-0 bg-background">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
