import { Outlet, Link, useLocation } from "react-router";
import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { UserNav } from "./UserNav";
import {
  Activity,
  Phone,
  Menu,
} from "lucide-react";
import logoSrc from "../../../assets/logo/logo.svg";
import { NotificationBell } from "../notifications/NotificationBell";

export function AgentLayout() {
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  const navItems = [
    { icon: Activity, label: "My Performance", path: "/agent" },
    { icon: Phone, label: "My Calls", path: "/agent/calls" },
  ];

  const getPageTitle = () => {
    if (location.pathname === "/agent") return "My Performance";
    if (location.pathname === "/agent/calls") return "My Calls";
    if (location.pathname.includes("calls")) return "Call Detail";
    if (location.pathname.includes("notifications")) return "Notifications";
    return "My Performance";
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
          <Link to="/agent" className="flex items-center gap-2.5">
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
              Agent
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
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
            {/* Top Group: Role Badge & Nav */}
            <div className="space-y-6">
              {!collapsed && (
                <div className="px-4">
                  <div className="bg-success/10 border border-success/20 rounded-xl p-3.5 transition-all shadow-sm">
                    <div className="text-[10px] font-bold text-success uppercase tracking-widest mb-1 opacity-80">
                      Agent Portal
                    </div>
                    <div className="text-[12px] text-foreground font-semibold leading-tight">
                      Personal view only
                    </div>
                  </div>
                </div>
              )}

              <nav className="px-2 space-y-1.5">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  const isActive = location.pathname === item.path || 
                    (item.path === "/agent/calls" && location.pathname.includes("/agent/calls"));
                  
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`flex items-center gap-3 px-3.5 h-11 rounded-xl transition-all ${
                        isActive
                          ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                          : "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                      }`}
                    >
                      <Icon className="w-[18px] h-[18px] flex-shrink-0" />
                      {!collapsed && (
                        <span className="text-[13.5px] font-semibold truncate">
                          {item.label}
                        </span>
                      )}
                    </Link>
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
