/**
 * API helpers for the notification + HITL feedback feature set.
 *
 * In USE_MOCK_API mode, calls are stubbed against sessionStorage so the demo
 * build keeps working end-to-end without a backend.
 */
import { apiFetch } from "./api";

const IS_CYPRESS = typeof window !== "undefined" && !!(window as { Cypress?: unknown }).Cypress;
const USE_MOCK_API = !IS_CYPRESS && import.meta.env.VITE_USE_MOCK_API !== "false";

// ── Types ────────────────────────────────────────────────────────────────────

export type NotificationType =
  | "evaluation_complete"
  | "agent_flag_pending"
  | "flag_approved"
  | "flag_rejected"
  | "manager_correction"
  | "feedback_applied";

export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  link_url: string | null;
  payload: Record<string, unknown> | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface EmotionFlagItem {
  kind: "emotion";
  review_id: string;
  interaction_id: string;
  agent_id: string;
  agent_name: string;
  agent_flagged_at: string;
  agent_flag_note: string | null;
  previous_emotion: string | null;
  new_emotion: string;
  llm_justification: string | null;
  confidence_score: number | null;
  jump_to_seconds: number;
}

export interface ComplianceFlagItem {
  kind: "compliance";
  review_id: string;
  interaction_id: string;
  agent_id: string;
  agent_name: string;
  agent_flagged_at: string;
  agent_flag_note: string | null;
  policy_id: string;
  policy_title: string | null;
  is_compliant: boolean;
  compliance_score: number;
  llm_reasoning: string | null;
  evidence_text: string | null;
}

export interface ReviewQueue {
  emotion: EmotionFlagItem[];
  compliance: ComplianceFlagItem[];
}

export interface EmotionReviewDecision {
  decision: "accept" | "reject";
  corrected_emotion?: string;
  corrected_justification?: string;
  manager_note?: string;
}

export interface ComplianceReviewDecision {
  decision: "accept" | "reject";
  corrected_is_compliant?: boolean;
  corrected_score?: number;
  manager_note?: string;
}

// ── Mock-mode store ──────────────────────────────────────────────────────────

const MOCK_NOTIFS_KEY = "vm_mock_notifications";
const MOCK_QUEUE_KEY = "vm_mock_review_queue";

function readMockNotifs(): NotificationItem[] {
  if (typeof sessionStorage === "undefined") return [];
  const raw = sessionStorage.getItem(MOCK_NOTIFS_KEY);
  if (raw) {
    try {
      return JSON.parse(raw) as NotificationItem[];
    } catch {
      /* fall through */
    }
  }
  // Seed a few demo notifications so the bell looks alive in mock mode.
  const seed: NotificationItem[] = [
    {
      id: "n-1",
      type: "evaluation_complete",
      title: "Call evaluation complete",
      body: "Interaction #4821 finished evaluation. Overall score 84.",
      link_url: "/manager/inspector/4821",
      payload: { interaction_id: "4821" },
      is_read: false,
      read_at: null,
      created_at: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
    },
    {
      id: "n-2",
      type: "agent_flag_pending",
      title: "Sara Kim flagged an emotion event",
      body: "Disagrees with 'angry' classification at 01:23.",
      link_url: "/manager/reviews",
      payload: { kind: "emotion" },
      is_read: false,
      read_at: null,
      created_at: new Date(Date.now() - 1000 * 60 * 47).toISOString(),
    },
  ];
  sessionStorage.setItem(MOCK_NOTIFS_KEY, JSON.stringify(seed));
  return seed;
}

function writeMockNotifs(items: NotificationItem[]): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(MOCK_NOTIFS_KEY, JSON.stringify(items));
}

function readMockQueue(): ReviewQueue {
  if (typeof sessionStorage === "undefined") return { emotion: [], compliance: [] };
  const raw = sessionStorage.getItem(MOCK_QUEUE_KEY);
  if (raw) {
    try {
      return JSON.parse(raw) as ReviewQueue;
    } catch {
      /* fall through */
    }
  }
  const seed: ReviewQueue = {
    emotion: [
      {
        kind: "emotion",
        review_id: "ev-mock-1",
        interaction_id: "4821",
        agent_id: "agent-sara",
        agent_name: "Sara Kim",
        agent_flagged_at: new Date(Date.now() - 1000 * 60 * 47).toISOString(),
        agent_flag_note: "Customer was joking, not angry. Tone was sarcastic.",
        previous_emotion: "neutral",
        new_emotion: "angry",
        llm_justification: "Sharp pitch rise and stress markers around 'this is ridiculous'.",
        confidence_score: 0.72,
        jump_to_seconds: 83.5,
      },
    ],
    compliance: [
      {
        kind: "compliance",
        review_id: "pc-mock-1",
        interaction_id: "4811",
        agent_id: "agent-luis",
        agent_name: "Luis Romero",
        agent_flagged_at: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
        agent_flag_note: "I did read the disclosure — see 02:14.",
        policy_id: "pol-disclosure",
        policy_title: "Mandatory disclosure script",
        is_compliant: false,
        compliance_score: 0.31,
        llm_reasoning: "No mention of recording disclosure detected in transcript.",
        evidence_text: null,
      },
    ],
  };
  sessionStorage.setItem(MOCK_QUEUE_KEY, JSON.stringify(seed));
  return seed;
}

function writeMockQueue(queue: ReviewQueue): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(MOCK_QUEUE_KEY, JSON.stringify(queue));
}

// ── Notifications API ────────────────────────────────────────────────────────

export async function listNotifications(opts?: { unread?: boolean; limit?: number }): Promise<NotificationItem[]> {
  if (USE_MOCK_API) {
    const items = readMockNotifs();
    const filtered = opts?.unread ? items.filter((n) => !n.is_read) : items;
    return filtered.slice(0, opts?.limit ?? 50);
  }
  const params = new URLSearchParams();
  if (opts?.unread) params.set("unread", "true");
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<NotificationItem[]>(`/notifications${qs ? `?${qs}` : ""}`);
}

export async function getUnreadCount(): Promise<number> {
  if (USE_MOCK_API) {
    return readMockNotifs().filter((n) => !n.is_read).length;
  }
  const res = await apiFetch<{ unread: number }>(`/notifications/unread-count`);
  return res.unread;
}

export async function markNotificationRead(id: string): Promise<void> {
  if (USE_MOCK_API) {
    const items = readMockNotifs().map((n) =>
      n.id === id ? { ...n, is_read: true, read_at: new Date().toISOString() } : n,
    );
    writeMockNotifs(items);
    return;
  }
  await apiFetch(`/notifications/${id}/read`, { method: "POST" });
}

export async function markAllNotificationsRead(): Promise<void> {
  if (USE_MOCK_API) {
    const now = new Date().toISOString();
    writeMockNotifs(readMockNotifs().map((n) => ({ ...n, is_read: true, read_at: n.read_at ?? now })));
    return;
  }
  await apiFetch(`/notifications/read-all`, { method: "POST" });
}

// ── Review queue API ─────────────────────────────────────────────────────────

export async function getReviewQueue(): Promise<ReviewQueue> {
  if (USE_MOCK_API) return readMockQueue();
  return apiFetch<ReviewQueue>(`/reviews/queue`);
}

export async function reviewEmotionFlag(eventId: string, decision: EmotionReviewDecision): Promise<void> {
  if (USE_MOCK_API) {
    const queue = readMockQueue();
    queue.emotion = queue.emotion.filter((e) => e.review_id !== eventId);
    writeMockQueue(queue);
    return;
  }
  await apiFetch(`/reviews/emotion/${eventId}`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

export async function reviewComplianceFlag(complianceId: string, decision: ComplianceReviewDecision): Promise<void> {
  if (USE_MOCK_API) {
    const queue = readMockQueue();
    queue.compliance = queue.compliance.filter((c) => c.review_id !== complianceId);
    writeMockQueue(queue);
    return;
  }
  await apiFetch(`/reviews/compliance/${complianceId}`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

// ── Manager-initiated corrections ────────────────────────────────────────────

export async function correctEmotion(payload: {
  emotion_event_id: string;
  corrected_emotion: string;
  corrected_justification?: string;
  correction_reason?: string;
}): Promise<{ feedback_id: string }> {
  if (USE_MOCK_API) return { feedback_id: `fb-${Date.now()}` };
  return apiFetch<{ feedback_id: string }>(`/feedback/emotion`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function correctCompliance(payload: {
  policy_compliance_id: string;
  corrected_is_compliant: boolean;
  corrected_score?: number;
  correction_reason?: string;
}): Promise<{ feedback_id: string }> {
  if (USE_MOCK_API) return { feedback_id: `fb-${Date.now()}` };
  return apiFetch<{ feedback_id: string }>(`/feedback/compliance`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ── Agent-side dispute helpers ───────────────────────────────────────────────

export async function disputeEmotionEvent(eventId: string, note?: string): Promise<void> {
  if (USE_MOCK_API) return;
  await apiFetch(`/interactions/emotion-events/${eventId}/dispute`, {
    method: "POST",
    body: JSON.stringify({ agent_flag_note: note ?? null }),
  });
}

export async function retractEmotionDispute(eventId: string): Promise<void> {
  if (USE_MOCK_API) return;
  await apiFetch(`/interactions/emotion-events/${eventId}/dispute`, { method: "DELETE" });
}

export async function disputeCompliance(complianceId: string, note?: string): Promise<void> {
  if (USE_MOCK_API) return;
  await apiFetch(`/policy-compliance/${complianceId}/dispute`, {
    method: "POST",
    body: JSON.stringify({ agent_flag_note: note ?? null }),
  });
}

export async function retractComplianceDispute(complianceId: string): Promise<void> {
  if (USE_MOCK_API) return;
  await apiFetch(`/policy-compliance/${complianceId}/dispute`, { method: "DELETE" });
}
