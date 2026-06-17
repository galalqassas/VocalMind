import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { Button } from "../ui/button";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "../../services/feedbackLoop";

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function NotificationsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listNotifications({ unread: filter === "unread", limit: 100 }));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleClick = async (item: NotificationItem) => {
    if (!item.is_read) {
      try {
        await markNotificationRead(item.id);
      } catch {
        /* ignore */
      }
    }
    if (item.link_url) navigate(item.link_url);
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
    } finally {
      refresh();
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Bell className="w-5 h-5 text-primary mt-0.5" />
          <div>
            <h2 className="text-[18px] font-bold text-foreground">Notifications</h2>
            <p className="text-[13px] text-muted-foreground">Updates from your evaluations and review queue.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant={filter === "all" ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter("all")}
          >
            All
          </Button>
          <Button
            variant={filter === "unread" ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter("unread")}
          >
            Unread
          </Button>
          <Button variant="ghost" size="sm" onClick={handleMarkAllRead}>
            <CheckCheck className="w-3.5 h-3.5 mr-1" /> Mark all read
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-10 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Loading…
        </div>
      ) : items.length === 0 ? (
        <div className="text-center text-sm text-muted-foreground py-16 border border-dashed border-border rounded-xl">
          No notifications.
        </div>
      ) : (
        <div className="border border-border rounded-xl divide-y divide-border bg-card overflow-hidden">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => handleClick(item)}
              className={`w-full text-left p-4 flex items-start gap-3 hover:bg-accent/40 transition-colors ${
                item.is_read ? "" : "bg-primary/5"
              }`}
            >
              <span
                className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${
                  item.is_read ? "bg-transparent border border-border" : "bg-primary"
                }`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[14px] font-semibold text-foreground">{item.title}</div>
                  <div className="text-[11px] text-muted-foreground whitespace-nowrap">{formatWhen(item.created_at)}</div>
                </div>
                {item.body && <div className="text-[12.5px] text-muted-foreground mt-0.5">{item.body}</div>}
                {item.link_url && (
                  <Link to={item.link_url} onClick={(e) => e.stopPropagation()} className="text-[11px] text-primary hover:underline">
                    Open →
                  </Link>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
