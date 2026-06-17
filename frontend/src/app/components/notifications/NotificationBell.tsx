import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Bell, CheckCheck } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "../../services/feedbackLoop";

const POLL_INTERVAL_MS = 30_000;

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const navigate = useNavigate();
  const location = useLocation();
  const isAgent = location.pathname.startsWith("/agent");
  const allNotificationsHref = isAgent ? "/agent/notifications" : "/manager/notifications";
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [count, list] = await Promise.all([
        getUnreadCount(),
        listNotifications({ limit: 10 }),
      ]);
      setUnread(count);
      setItems(list);
    } catch {
      /* poll failures are silent; will retry next tick */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(t);
  }, [refresh]);

  const handleClick = async (item: NotificationItem) => {
    setOpen(false);
    if (!item.is_read) {
      try {
        await markNotificationRead(item.id);
      } catch {
        /* ignore — UI will resync on next poll */
      }
    }
    if (item.link_url) navigate(item.link_url);
    refresh();
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
    } finally {
      refresh();
    }
  };

  const badgeText = unread > 9 ? "9+" : String(unread);

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={`Notifications (${unread} unread)`}
          data-cy="notification-bell"
          className="relative w-8 h-8 flex items-center justify-center bg-accent/30 border border-border rounded-lg hover:bg-accent transition-colors"
        >
          <Bell className="w-4 h-4 text-muted-foreground" />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-[10px] font-bold text-white bg-red-500 rounded-full border border-card">
              {badgeText}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80 bg-card border-border shadow-lg" align="end">
        <div className="flex items-center justify-between px-2 py-1">
          <DropdownMenuLabel className="px-1">Notifications</DropdownMenuLabel>
          {unread > 0 && (
            <button
              onClick={handleMarkAllRead}
              className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
            >
              <CheckCheck className="w-3 h-3" />
              Mark all read
            </button>
          )}
        </div>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">No notifications</div>
        ) : (
          <div className="max-h-[360px] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => handleClick(item)}
                className={`w-full text-left px-3 py-2.5 flex items-start gap-2 hover:bg-accent/40 transition-colors ${
                  item.is_read ? "" : "bg-primary/5"
                }`}
              >
                <span
                  className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${
                    item.is_read ? "bg-transparent" : "bg-primary"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-semibold text-foreground truncate">{item.title}</div>
                  {item.body && (
                    <div className="text-[12px] text-muted-foreground line-clamp-2">{item.body}</div>
                  )}
                  <div className="text-[10px] text-muted-foreground mt-1">{formatRelativeTime(item.created_at)}</div>
                </div>
              </button>
            ))}
          </div>
        )}
        <DropdownMenuSeparator />
        <Link
          to={allNotificationsHref}
          onClick={() => setOpen(false)}
          className="block px-3 py-2 text-[12px] text-center text-primary hover:underline"
        >
          View all
        </Link>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
