import { Link, useParams } from "react-router";
import {
  ArrowLeft, Play, Pause, SkipBack, SkipForward,
  Loader2, AlertTriangle as AlertTriangleIcon, RefreshCw,
  Flag, ChevronDown, ChevronRight, Activity,
  Brain, Shield, FileWarning, CheckCircle2, XCircle, Volume2, VolumeX,
  Quote, Info, Gauge, BookOpen, GitBranch, AlertCircle,
} from "lucide-react";
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  getInteractionDetail, getAudioUrl, reprocessInteraction,
  getInteractionProcessingStatus,
  type InteractionDetail, type UtteranceData, type EmotionEventData,
  type LLMEvidenceCitation, type ProcessingStatusResult,
} from "../../services/api";
import { EvidenceAnchoredExplainabilityPanel } from "./EvidenceAnchoredExplainabilityPanel";

// ── Constants ────────────────────────────────────────────────────────────────

const EMOTION_SCORE: Record<string, number> = {
  angry: 0, frustrated: 1, sad: 2, neutral: 3, happy: 4,
};
const EMOTION_LABELS = ["Angry", "Frustrated", "Sad", "Neutral", "Happy"];

const EMOTION_ALIASES: Record<string, string> = {
  fearful: "frustrated", surprised: "neutral", disgusted: "angry",
};

const normalizeEmotion = (raw: string): string => EMOTION_ALIASES[raw] ?? raw;

const EMOTION_STYLE: Record<string, { color: string; label: string }> = {
  neutral: { color: "var(--muted-foreground)", label: "Neutral" },
  happy: { color: "#10B981", label: "Happy" },
  angry: { color: "#EF4444", label: "Angry" },
  frustrated: { color: "#F59E0B", label: "Frustrated" },
  sad: { color: "#8B5CF6", label: "Sad" },
};

function getEmotionStyle(raw: string) {
  return EMOTION_STYLE[normalizeEmotion(raw)] ?? EMOTION_STYLE.neutral;
}

function formatSeconds(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function getScoreColor(score: number): string {
  if (score >= 85) return "var(--success)";
  if (score >= 70) return "var(--primary)";
  return "var(--destructive)";
}

// ── Timeline merging ─────────────────────────────────────────────────────────

type TimelineItem =
  | { kind: "utterance"; time: number; data: UtteranceData }
  | { kind: "shift"; time: number; data: EmotionEventData };

function buildTimeline(utterances: UtteranceData[], events: EmotionEventData[]): TimelineItem[] {
  const items: TimelineItem[] = [
    ...utterances.map((u): TimelineItem => ({ kind: "utterance", time: u.startTime, data: u })),
    ...events.map((e): TimelineItem => ({ kind: "shift", time: e.jumpToSeconds, data: e })),
  ];
  items.sort((a, b) => a.time - b.time);
  return items;
}

// ── Emotion chart data ───────────────────────────────────────────────────────

interface EmotionPoint {
  time: number;
  customer?: number;
  agent?: number;
}

function buildEmotionChartData(utterances: UtteranceData[]): EmotionPoint[] {
  return [...utterances]
    .sort((a, b) => a.startTime - b.startTime)
    .map((u) => {
      const score = EMOTION_SCORE[normalizeEmotion(u.emotion)] ?? 3;
      return {
        time: u.startTime,
        ...(u.speaker === "agent" ? { agent: score } : { customer: score }),
      };
    });
}

// ── Custom chart tooltip ─────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-[11px] text-muted-foreground mb-1">{formatSeconds(label)}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="text-[12px] font-semibold" style={{ color: p.color }}>
          {p.name}: {EMOTION_LABELS[p.value] ?? "Unknown"}
        </p>
      ))}
    </div>
  );
}

// ── Pipeline Helper Components ───────────────────────────────────────────────

function ConfidenceBadge({ score, label = "Confidence" }: { score?: number | null; label?: string }) {
  if (score == null) return null;
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const color = pct >= 80 ? "text-emerald-500" : pct >= 50 ? "text-amber-500" : "text-red-400";
  return (
    <span className={`text-[10px] font-bold ${color}`}>
      {label} {pct}%
    </span>
  );
}

function InsufficientEvidenceWarning({ flag }: { flag?: boolean }) {
  if (!flag) return null;
  return (
    <div className="flex items-center gap-1.5 rounded-md bg-amber-500/8 border border-amber-500/15 px-2.5 py-1.5">
      <AlertCircle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
      <span className="text-[11px] text-amber-500 font-medium">Insufficient evidence — results may be unreliable</span>
    </div>
  );
}

function EvidenceQuotes({ quotes, label = "Evidence" }: { quotes?: string[]; label?: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!quotes?.length) return null;
  const visible = expanded ? quotes : quotes.slice(0, 2);
  return (
    <div className="rounded-lg bg-muted/30 border border-border/50 p-2.5">
      <button type="button" onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 w-full text-left mb-1.5">
        <Quote className="w-3 h-3 text-muted-foreground shrink-0" />
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider flex-1">{label} ({quotes.length})</span>
        {quotes.length > 2 && (
          <span className="text-[10px] text-primary font-semibold">{expanded ? "Show less" : `+${quotes.length - 2} more`}</span>
        )}
      </button>
      <div className="space-y-1">
        {visible.map((q, i) => (
          <p key={i} className="text-[11px] italic text-foreground/70 leading-relaxed pl-4 border-l-2 border-border">
            &ldquo;{q}&rdquo;
          </p>
        ))}
      </div>
    </div>
  );
}

const CITATION_ICONS: Record<string, { char: string; color: string }> = {
  transcript: { char: "T", color: "bg-blue-500/15 text-blue-400" },
  policy: { char: "P", color: "bg-purple-500/15 text-purple-400" },
  sop: { char: "S", color: "bg-teal-500/15 text-teal-400" },
  acoustic: { char: "A", color: "bg-amber-500/15 text-amber-400" },
  kb: { char: "K", color: "bg-emerald-500/15 text-emerald-400" },
};

function CitationsList({ citations, onJumpTo, utterances }: {
  citations?: LLMEvidenceCitation[];
  onJumpTo: (seconds: number) => void;
  utterances: UtteranceData[];
}) {
  const [expanded, setExpanded] = useState(false);
  if (!citations?.length) return null;
  const visible = expanded ? citations : citations.slice(0, 3);
  return (
    <div className="space-y-1.5">
      <button type="button" onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-left">
        <GitBranch className="w-3 h-3 text-muted-foreground" />
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Citations ({citations.length})</span>
        {citations.length > 3 && (
          <span className="text-[10px] text-primary font-semibold">{expanded ? "less" : `+${citations.length - 3}`}</span>
        )}
      </button>
      {visible.map((c, i) => {
        const icon = CITATION_ICONS[c.source] ?? { char: "?", color: "bg-muted text-muted-foreground" };
        const utt = c.utteranceIndex != null ? utterances[c.utteranceIndex] : null;
        return (
          <div key={i} className="flex items-start gap-2 text-[11px]">
            <span className={`w-4 h-4 rounded text-[9px] font-bold flex items-center justify-center shrink-0 mt-0.5 ${icon.color}`}>
              {icon.char}
            </span>
            <div className="flex-1 min-w-0">
              <span className="text-foreground/70 italic">&ldquo;{c.quote}&rdquo;</span>
              {c.speaker && <span className="text-muted-foreground ml-1">— {c.speaker}</span>}
            </div>
            {utt && (
              <button type="button" onClick={() => onJumpTo(utt.startTime)}
                className="text-[9px] text-primary font-bold hover:underline shrink-0">
                {utt.timestamp}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EfficiencyGauge({ score }: { score?: number }) {
  if (score == null) return null;
  const clamped = Math.max(0, Math.min(10, score));
  const pct = clamped * 10;
  const color = pct >= 80 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#EF4444";
  return (
    <div className="flex items-center gap-2.5">
      <Gauge className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-bold tabular-nums" style={{ color }}>{clamped}/10</span>
    </div>
  );
}

// ── Score Ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score, size = 80 }: { score: number; size?: number }) {
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const color = getScoreColor(score);
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="w-full h-full -rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth="6" />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={color} strokeWidth="6" strokeLinecap="round"
          strokeDasharray={`${(score / 100) * circ} ${circ}`}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-lg font-bold" style={{ color }}>{score}%</span>
      </div>
    </div>
  );
}

// ── Collapsible Section ──────────────────────────────────────────────────────

function CollapsibleCard({
  title, icon, defaultOpen = true, badge, children,
}: {
  title: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
      >
        {icon}
        <span className="text-[13px] font-bold text-foreground flex-1">{title}</span>
        {badge}
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && <div className="px-4 pb-4 space-y-3">{children}</div>}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

export function SessionDetail() {
  const { id } = useParams();
  const [data, setData] = useState<InteractionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const [audioEpoch, setAudioEpoch] = useState(0);

  // Audio player state
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioObjectUrlRef = useRef<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);

  // Transcript state
  const [followAudio, setFollowAudio] = useState(true);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const [flaggedItems, setFlaggedItems] = useState<Set<string>>(new Set());
  const [feedbackDone, setFeedbackDone] = useState<Set<string>>(new Set());

  // Processing poll state
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatusResult | null>(null);

  // ── Data fetch ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!id) return;
    getInteractionDetail(id)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  // ── Processing status poll ─────────────────────────────────────────────
  const interactionStatus = data?.interaction?.status ?? "";
  const isProcessingNow = ["processing", "pending"].includes(interactionStatus.toLowerCase());
  useEffect(() => {
    if (!id || !isProcessingNow) { setProcessingStatus(null); return; }
    let cancelled = false;
    const poll = () => {
      void getInteractionProcessingStatus(id)
        .then((s) => {
          if (cancelled) return;
          setProcessingStatus(s);
          const done = !["processing", "pending"].includes(s.status.toLowerCase());
          if (done) {
            void getInteractionDetail(id, { skipCache: true }).then((d) => { if (!cancelled) setData(d); });
          }
        })
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 6000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [id, isProcessingNow]);

  // ── Audio fetch ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!id) { setAudioSrc(null); return; }
    let cancelled = false;
    const revoke = () => {
      if (audioObjectUrlRef.current) {
        URL.revokeObjectURL(audioObjectUrlRef.current);
        audioObjectUrlRef.current = null;
      }
    };
    revoke();
    setAudioSrc(null);

    void fetch(getAudioUrl(id), { credentials: "include" })
      .then((res) => { if (!res.ok) throw new Error(`audio ${res.status}`); return res.blob(); })
      .then((blob) => {
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        audioObjectUrlRef.current = url;
        setAudioSrc(url);
      })
      .catch(() => { if (!cancelled) setAudioSrc(null); });

    return () => { cancelled = true; revoke(); };
  }, [id, audioEpoch]);

  // ── Audio event listeners ───────────────────────────────────────────────
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => setCurrentTime(a.currentTime);
    const onDur = () => setDuration(a.duration || 0);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnd = () => setIsPlaying(false);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onDur);
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onEnd);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onDur);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onEnd);
    };
  }, [audioSrc]);

  // ── Auto-scroll transcript ──────────────────────────────────────────────
  useEffect(() => {
    if (!followAudio || !transcriptRef.current || !data) return;
    const el = transcriptRef.current.querySelector(`[data-active="true"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [currentTime, followAudio, data]);

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleJumpTo = useCallback((seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      audioRef.current.play().catch(() => {});
    }
  }, []);

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (isPlaying) audioRef.current.pause();
    else audioRef.current.play().catch(() => {});
  };

  const skip = (delta: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, Math.min(duration, audioRef.current.currentTime + delta));
  };

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!audioRef.current || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    audioRef.current.currentTime = ((e.clientX - rect.left) / rect.width) * duration;
  };

  const handleReprocess = async () => {
    if (!id || reprocessing) return;
    setActionError(null);
    setReprocessing(true);
    try {
      await reprocessInteraction(id);
      const refreshed = await getInteractionDetail(id, { skipCache: true });
      setData(refreshed);
      setAudioEpoch((n) => n + 1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to reprocess";
      if (msg.includes("409")) {
        try {
          await reprocessInteraction(id, { force: true });
          const refreshed = await getInteractionDetail(id, { skipCache: true });
          setData(refreshed);
          setAudioEpoch((n) => n + 1);
          return;
        } catch { setActionError("Already processing. Please wait."); }
      } else { setActionError(msg); }
    } finally { setReprocessing(false); }
  };

  const toggleFlag = (itemId: string) => setFlaggedItems((s) => { const n = new Set(s); n.add(itemId); return n; });
  const submitFeedback = (itemId: string) => setFeedbackDone((s) => { const n = new Set(s); n.add(itemId); return n; });

  // ── Computed ────────────────────────────────────────────────────────────
  const interaction = data?.interaction;
  const utterances = data?.utterances ?? [];
  const emotionEvents = data?.emotionEvents ?? [];
  const policyViolations = data?.policyViolations ?? [];

  const timeline = useMemo(() => buildTimeline(utterances, emotionEvents), [utterances, emotionEvents]);
  const chartData = useMemo(() => buildEmotionChartData(utterances), [utterances]);

  const activeUtteranceId = useMemo(() => {
    if (!followAudio || !utterances.length) return null;
    for (let i = utterances.length - 1; i >= 0; i--) {
      if (currentTime >= utterances[i].startTime) return utterances[i].id;
    }
    return null;
  }, [currentTime, followAudio, utterances]);

  const emotionTrigger = data?.emotionTriggers ?? data?.llmTriggers ?? null;
  const ragCompliance = data?.ragCompliance ?? null;
  const ragProcess = ragCompliance?.processAdherence ?? data?.llmTriggers?.processAdherence ?? null;
  const ragNli = ragCompliance?.nliPolicy ?? data?.llmTriggers?.nliPolicy ?? null;
  const explainability = emotionTrigger?.explainability ?? ragCompliance?.explainability ?? data?.llmTriggers?.explainability ?? null;

  const hasAnalysisData = !!(
    emotionTrigger?.emotionShift || ragProcess || ragNli ||
    policyViolations.length > 0 || data?.emotionComparison || explainability
  );

  const pipelineErrors: string[] = [];
  if (emotionTrigger && !emotionTrigger.available && emotionTrigger.error) pipelineErrors.push(`Emotion: ${emotionTrigger.error}`);
  if (ragCompliance && !ragCompliance.available && ragCompliance.error) pipelineErrors.push(`Compliance: ${ragCompliance.error}`);
  if (data?.llmTriggers && !data.llmTriggers.available && data.llmTriggers.error) pipelineErrors.push(`LLM: ${data.llmTriggers.error}`);

  const isFailedInteraction = String(interaction?.status || "").toLowerCase() === "failed";

  // ── Loading / Error ─────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <span className="ml-3 text-muted-foreground text-sm">Loading session...</span>
      </div>
    );
  }

  if (error || !data || !interaction) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <AlertTriangleIcon className="w-10 h-10 text-amber-500 mx-auto mb-3" />
          <p className="text-foreground text-sm">Failed to load session</p>
          <p className="text-muted-foreground/80 text-xs mt-1">{error}</p>
        </div>
      </div>
    );
  }

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="p-4 md:p-6 space-y-5 max-w-[1440px] mx-auto">

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/manager/inspector" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary hover:underline">
          <ArrowLeft className="w-4 h-4" /> Back to Session Inspector
        </Link>
        <button type="button" onClick={() => void handleReprocess()} disabled={reprocessing}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-[12px] font-semibold text-foreground hover:bg-muted disabled:opacity-50">
          <RefreshCw className={`h-3.5 w-3.5 ${reprocessing ? "animate-spin" : ""}`} />
          {reprocessing ? "Reprocessing..." : "Reprocess"}
        </button>
      </div>

      {actionError && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2.5 text-[12px] font-medium text-destructive">{actionError}</div>
      )}

      {/* ── Processing banner ─────────────────────────────────────────────── */}
      {isProcessingNow && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
          <div className="flex items-center gap-2.5 mb-2">
            <Loader2 className="w-4 h-4 text-primary animate-spin shrink-0" />
            <p className="text-[13px] font-semibold text-foreground">Pipeline processing — page will refresh automatically</p>
          </div>
          {processingStatus && processingStatus.jobs.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 mt-2">
              {processingStatus.jobs.map((job) => {
                const s = job.status.toLowerCase();
                const color = s === "completed" ? "text-emerald-500" : s === "failed" ? "text-red-400" : s === "running" ? "text-primary" : "text-muted-foreground";
                const icon = s === "completed" ? "✓" : s === "failed" ? "✗" : s === "running" ? "⟳" : "·";
                return (
                  <div key={job.stage} className="flex items-center gap-1.5 text-[11px]">
                    <span className={`font-bold ${color} w-3`}>{icon}</span>
                    <span className="text-muted-foreground capitalize">{job.stage.replace(/_/g, " ")}</span>
                    {job.retryCount > 0 && <span className="text-amber-500 text-[10px]">×{job.retryCount}</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {data.processingFailures && data.processingFailures.length > 0 && (
        <div className="rounded-lg border border-destructive/25 bg-destructive/5 px-4 py-3 text-[12px]">
          <p className="font-semibold text-destructive mb-1.5">Processing errors</p>
          <ul className="list-disc pl-4 text-muted-foreground space-y-0.5">
            {data.processingFailures.map((f, i) => (
              <li key={`${f.stage}-${i}`}>
                <span className="font-mono text-[11px] text-foreground">{f.stage}</span>
                {f.errorMessage ? `: ${f.errorMessage}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Header Card ──────────────────────────────────────────────────── */}
      <div className="bg-card rounded-xl border border-border p-5">
        <div className="flex items-start gap-5">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-1">
              <h2 className="text-xl font-bold text-foreground truncate">{interaction.agentName}</h2>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
                interaction.resolved
                  ? "bg-emerald-500/10 text-emerald-500"
                  : "bg-red-500/10 text-red-500"
              }`}>
                {interaction.resolved ? "Resolved" : "Unresolved"}
              </span>
            </div>
            <p className="text-[12px] text-muted-foreground">
              {interaction.date} &middot; {interaction.time} &middot; {interaction.duration} &middot; {interaction.language}
            </p>

            {/* Sub-scores */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              {([
                { label: "Empathy", value: interaction.empathyScore, suffix: "%" },
                { label: "Policy", value: interaction.policyScore, suffix: "%" },
                { label: "Resolution", value: interaction.resolutionScore, suffix: "%" },
                { label: "Resp. Time", value: interaction.responseTime, suffix: "s" },
              ] as const).map((s) => (
                <div key={s.label} className="rounded-lg bg-muted/40 border border-border/50 px-3 py-2 text-center">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-0.5">{s.label}</div>
                  <div className="text-base font-bold" style={{ color: typeof s.value === "number" ? getScoreColor(s.value) : "var(--foreground)" }}>
                    {s.value}{typeof s.value === "number" ? s.suffix : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <ScoreRing score={interaction.overallScore} />
        </div>

        {/* ── Audio Player ───────────────────────────────────────────────── */}
        <div className="mt-4 pt-4 border-t border-border">
          {audioSrc ? (
            <>
              <audio ref={audioRef} src={audioSrc} preload="metadata" className="hidden" />
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1">
                  <button type="button" onClick={() => skip(-10)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
                    <SkipBack className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" onClick={togglePlay}
                    className="w-9 h-9 rounded-full bg-primary text-primary-foreground flex items-center justify-center hover:opacity-90 transition-opacity">
                    {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
                  </button>
                  <button type="button" onClick={() => skip(10)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
                    <SkipForward className="w-3.5 h-3.5" />
                  </button>
                </div>

                <span className="text-[11px] tabular-nums text-muted-foreground w-[80px] text-center shrink-0">
                  {formatSeconds(currentTime)} / {formatSeconds(duration || 0)}
                </span>

                <div className="flex-1 h-1.5 bg-muted rounded-full cursor-pointer group relative" onClick={handleSeek}>
                  <div className="h-full bg-primary rounded-full transition-all relative"
                    style={{ width: duration ? `${(currentTime / duration) * 100}%` : "0%" }}>
                    <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-primary rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow" />
                  </div>
                </div>

                <button type="button" onClick={() => { setMuted(!muted); if (audioRef.current) audioRef.current.muted = !muted; }}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
                  {muted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
                </button>
              </div>
            </>
          ) : (
            <p className="text-[12px] text-muted-foreground">Loading audio...</p>
          )}
        </div>
      </div>

      {/* ── Emotion Timeline ─────────────────────────────────────────────── */}
      {chartData.length > 0 && (
        <div className="bg-card rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-primary" />
            <h3 className="text-[14px] font-bold text-foreground">Emotion Timeline</h3>
            <span className="text-[11px] text-muted-foreground ml-auto">{utterances.length} utterances</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="time" type="number" domain={["dataMin", "dataMax"]}
                tickFormatter={formatSeconds}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={{ stroke: "var(--border)" }}
              />
              <YAxis
                domain={[0, 4]} ticks={[0, 1, 2, 3, 4]}
                tickFormatter={(v: number) => EMOTION_LABELS[v] ?? ""}
                tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={{ stroke: "var(--border)" }}
                width={72}
              />
              <RechartsTooltip content={<ChartTooltip />} />
              {currentTime > 0 && duration > 0 && (
                <ReferenceLine x={currentTime} stroke="var(--primary)" strokeDasharray="4 2" strokeWidth={1.5} />
              )}
              <Line
                dataKey="customer" name="Customer" type="monotone"
                stroke="#06B6D4" strokeWidth={2} dot={{ r: 2, fill: "#06B6D4" }}
                connectNulls activeDot={{ r: 4 }}
              />
              <Line
                dataKey="agent" name="Agent" type="monotone"
                stroke="#8B5CF6" strokeWidth={2} dot={{ r: 2, fill: "#8B5CF6" }}
                connectNulls activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-5 mt-2">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-0.5 rounded bg-[#06B6D4]" />
              <span className="text-[11px] text-muted-foreground">Customer</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-0.5 rounded bg-[#8B5CF6]" />
              <span className="text-[11px] text-muted-foreground">Agent</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Main Content ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">

        {/* ── Transcript (left) ────────────────────────────────────────── */}
        <div className="lg:col-span-7 bg-card rounded-xl border border-border p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-[14px] font-bold text-foreground">Transcript</h3>
              <p className="text-[11px] text-muted-foreground">{utterances.length} utterances</p>
            </div>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={followAudio} onChange={(e) => setFollowAudio(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-border accent-primary" />
              <span className="text-[11px] text-muted-foreground font-medium">Follow audio</span>
            </label>
          </div>

          <div ref={transcriptRef} className="space-y-1 max-h-[600px] overflow-y-auto pr-1 scroll-smooth">
            {timeline.map((item) => {
              if (item.kind === "shift") {
                const e = item.data;
                return (
                  <div key={`shift-${e.id}`} className="flex items-center gap-2 py-1.5 px-2">
                    <div className="flex-1 h-px bg-border" />
                    <button type="button" onClick={() => handleJumpTo(e.jumpToSeconds)}
                      className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground hover:text-primary transition-colors shrink-0">
                      <Activity className="w-3 h-3" />
                      <span className="capitalize">{e.fromEmotion}</span>
                      <span>&rarr;</span>
                      <span className="capitalize">{e.toEmotion}</span>
                      <span className="text-muted-foreground/60">&middot;</span>
                      <span className="uppercase">{e.speaker}</span>
                      <span className="text-muted-foreground/60">&middot;</span>
                      <span>{e.timestamp}</span>
                    </button>
                    <div className="flex-1 h-px bg-border" />
                  </div>
                );
              }

              const u = item.data;
              const isAgent = u.speaker === "agent";
              const emotionStyle = getEmotionStyle(u.emotion);
              const isActive = u.id === activeUtteranceId;

              return (
                <div key={u.id} data-active={isActive}
                  className={`flex gap-2.5 py-1.5 rounded-lg transition-colors ${isActive ? "bg-primary/5" : ""} ${isAgent ? "" : "flex-row-reverse"}`}>
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                    isAgent ? "bg-primary/15 text-primary" : "bg-emerald-500/15 text-emerald-500"
                  }`}>
                    {isAgent ? "A" : "C"}
                  </div>
                  <div className={`flex-1 min-w-0 px-3 py-2 rounded-xl text-[13px] ${
                    isAgent ? "bg-primary/5 rounded-tl-sm" : "bg-emerald-500/5 rounded-tr-sm"
                  }`}>
                    <div className="flex items-center justify-between gap-2 mb-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-foreground/80 text-[12px]">{isAgent ? interaction.agentName : "Customer"}</span>
                        <span className="rounded-full px-1.5 py-px text-[9px] font-semibold"
                          style={{ backgroundColor: `color-mix(in srgb, ${emotionStyle.color} 12%, transparent)`, color: emotionStyle.color }}>
                          {emotionStyle.label}
                        </span>
                      </div>
                      <button type="button" onClick={() => handleJumpTo(u.startTime)}
                        className="text-[10px] tabular-nums text-muted-foreground hover:text-primary transition-colors shrink-0">
                        {u.timestamp}
                      </button>
                    </div>
                    <p className="text-foreground leading-relaxed">{u.text}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Analysis Sidebar (right) ─────────────────────────────────── */}
        <div className="lg:col-span-5 space-y-4 lg:sticky lg:top-6 self-start">

          {!hasAnalysisData && (
            <div className="bg-card rounded-xl border border-border p-6 text-center space-y-3">
              <Brain className="w-8 h-8 text-muted-foreground/40 mx-auto" />
              <div>
                <p className="text-[13px] font-semibold text-foreground">No Analysis Available</p>
                <p className="text-[11px] text-muted-foreground mt-1">
                  Pipeline data hasn&apos;t been generated yet. Click Reprocess to run the evaluation pipeline.
                </p>
              </div>
              {pipelineErrors.length > 0 && (
                <div className="rounded-lg bg-red-500/5 border border-red-500/10 p-2.5 text-left">
                  <p className="text-[10px] font-semibold text-red-400 uppercase tracking-wider mb-1">Pipeline Errors</p>
                  {pipelineErrors.map((err, i) => (
                    <p key={i} className="text-[11px] text-muted-foreground">{err}</p>
                  ))}
                </div>
              )}
              <button type="button" onClick={() => void handleReprocess()} disabled={reprocessing}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-4 text-[12px] font-semibold text-primary hover:bg-primary/10 disabled:opacity-50 mx-auto">
                <RefreshCw className={`h-3.5 w-3.5 ${reprocessing ? "animate-spin" : ""}`} />
                {reprocessing ? "Processing..." : "Run Pipeline"}
              </button>
            </div>
          )}

          {/* Emotion Analysis (LLM Trigger) */}
          {emotionTrigger?.emotionShift && (
            <CollapsibleCard title="Emotion Analysis" icon={<Brain className="w-4 h-4 text-purple-400" />}
              badge={
                <div className="flex items-center gap-2">
                  <ConfidenceBadge score={emotionTrigger.emotionShift.confidenceScore} />
                  <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                    emotionTrigger.emotionShift.isDissonanceDetected
                      ? "bg-amber-500/10 text-amber-500" : "bg-emerald-500/10 text-emerald-500"
                  }`}>
                    {emotionTrigger.emotionShift.isDissonanceDetected ? "Dissonance" : "Aligned"}
                  </span>
                </div>
              }>
              <div className="space-y-2.5">
                <InsufficientEvidenceWarning flag={emotionTrigger.emotionShift.insufficientEvidence} />

                {emotionTrigger.emotionShift.currentCustomerEmotion && (
                  <div className="rounded-lg bg-primary/5 border border-primary/10 p-2.5">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Info className="w-3 h-3 text-primary" />
                      <span className="text-[10px] font-semibold text-primary uppercase tracking-wider">Current Customer Emotion</span>
                    </div>
                    <p className="text-[13px] font-semibold text-foreground capitalize">{emotionTrigger.emotionShift.currentCustomerEmotion}</p>
                    {emotionTrigger.emotionShift.currentEmotionReasoning && (
                      <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{emotionTrigger.emotionShift.currentEmotionReasoning}</p>
                    )}
                  </div>
                )}

                {emotionTrigger.emotionShift.dissonanceType && (
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">Type:</span>
                    <span className="text-[11px] font-semibold text-foreground">{emotionTrigger.emotionShift.dissonanceType}</span>
                  </div>
                )}
                <p className="text-[12px] text-muted-foreground leading-relaxed">{emotionTrigger.emotionShift.rootCause}</p>

                {emotionTrigger.emotionShift.counterfactualCorrection && (
                  <div className="rounded-lg bg-muted/40 border border-border/50 p-2.5">
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Counterfactual</p>
                    <p className="text-[12px] text-foreground italic leading-relaxed">{emotionTrigger.emotionShift.counterfactualCorrection}</p>
                  </div>
                )}

                <EvidenceQuotes quotes={emotionTrigger.emotionShift.evidenceQuotes} />
                <CitationsList citations={emotionTrigger.emotionShift.citations} onJumpTo={handleJumpTo} utterances={utterances} />

                {emotionTrigger.derived && (
                  <div className="rounded-lg bg-muted/20 border border-border/40 p-2.5 space-y-1.5">
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Derived Signals</p>
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <span className="text-muted-foreground">Acoustic:</span>
                        <span className="ml-1 font-semibold text-foreground capitalize">{emotionTrigger.derived.acousticEmotion}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Fused:</span>
                        <span className="ml-1 font-semibold text-foreground capitalize">{emotionTrigger.derived.fusedEmotion}</span>
                      </div>
                    </div>
                    {emotionTrigger.derived.agentStatement && (
                      <p className="text-[11px] text-foreground/70 italic border-l-2 border-border pl-2">
                        &ldquo;{emotionTrigger.derived.agentStatement}&rdquo;
                      </p>
                    )}
                  </div>
                )}
              </div>
            </CollapsibleCard>
          )}

          {/* RAG Compliance - Process Adherence */}
          {ragProcess && (
            <CollapsibleCard title="Process Adherence" icon={<Shield className="w-4 h-4 text-blue-400" />}
              badge={
                <div className="flex items-center gap-2">
                  <ConfidenceBadge score={ragProcess.confidenceScore} />
                  <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                    ragProcess.isResolved ? "bg-emerald-500/10 text-emerald-500" : "bg-red-500/10 text-red-500"
                  }`}>
                    {ragProcess.isResolved ? "Resolved" : "Needs follow-up"}
                  </span>
                </div>
              }>
              <div className="space-y-2.5">
                <InsufficientEvidenceWarning flag={ragProcess.insufficientEvidence} />

                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">Topic:</span>
                  <span className="text-[11px] font-semibold text-foreground">{ragProcess.detectedTopic}</span>
                </div>

                <EfficiencyGauge score={ragProcess.efficiencyScore} />

                <p className="text-[12px] text-muted-foreground leading-relaxed">{ragProcess.justification}</p>

                {ragProcess.missingSopSteps.length > 0 && (
                  <div className="rounded-lg bg-red-500/5 border border-red-500/10 p-2.5">
                    <p className="text-[10px] font-semibold text-red-400 uppercase tracking-wider mb-1">Missing SOP Steps</p>
                    <ul className="space-y-1">
                      {ragProcess.missingSopSteps.map((step, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-[12px] text-muted-foreground">
                          <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                          {step}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <EvidenceQuotes quotes={ragProcess.evidenceQuotes} />
                <CitationsList citations={ragProcess.citations} onJumpTo={handleJumpTo} utterances={utterances} />
              </div>
            </CollapsibleCard>
          )}

          {/* RAG Compliance - NLI Policy */}
          {ragNli && (
            <CollapsibleCard title="Policy Inference (NLI)" icon={<FileWarning className="w-4 h-4 text-teal-400" />}
              badge={
                <div className="flex items-center gap-2">
                  <ConfidenceBadge score={ragNli.confidenceScore} />
                  <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                    ragNli.nliCategory === "Entailment"
                      ? "bg-emerald-500/10 text-emerald-500"
                      : ragNli.nliCategory === "Contradiction"
                        ? "bg-red-500/10 text-red-500"
                        : "bg-amber-500/10 text-amber-500"
                  }`}>
                    {ragNli.nliCategory}
                  </span>
                </div>
              }>
              <div className="space-y-2.5">
                <InsufficientEvidenceWarning flag={ragNli.insufficientEvidence} />

                {(ragNli.policyVersion || ragNli.policyCategory || ragNli.policyEffectiveAt) && (
                  <div className="rounded-lg bg-muted/30 border border-border/50 p-2.5 space-y-1">
                    <div className="flex items-center gap-1.5 mb-1">
                      <BookOpen className="w-3 h-3 text-teal-400" />
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Policy Metadata</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                      {ragNli.policyVersion && (
                        <>
                          <span className="text-muted-foreground">Version:</span>
                          <span className="font-semibold text-foreground">{ragNli.policyVersion}</span>
                        </>
                      )}
                      {ragNli.policyCategory && (
                        <>
                          <span className="text-muted-foreground">Category:</span>
                          <span className="font-semibold text-foreground">{ragNli.policyCategory}</span>
                        </>
                      )}
                      {ragNli.policyEffectiveAt && (
                        <>
                          <span className="text-muted-foreground">Effective:</span>
                          <span className="font-semibold text-foreground">{ragNli.policyEffectiveAt}</span>
                        </>
                      )}
                    </div>
                    {ragNli.conflictResolutionApplied && (
                      <div className="flex items-center gap-1.5 mt-1">
                        <AlertCircle className="w-3 h-3 text-amber-500" />
                        <span className="text-[10px] text-amber-500 font-medium">Conflict resolution applied</span>
                      </div>
                    )}
                  </div>
                )}

                <p className="text-[12px] text-muted-foreground leading-relaxed">{ragNli.justification}</p>

                {ragNli.policyAlignmentScore != null && (
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">Alignment:</span>
                    <span className="text-[12px] font-bold" style={{ color: getScoreColor(ragNli.policyAlignmentScore) }}>
                      {ragNli.policyAlignmentScore}%
                    </span>
                  </div>
                )}

                <EvidenceQuotes quotes={ragNli.evidenceQuotes} />
                <CitationsList citations={ragNli.citations} onJumpTo={handleJumpTo} utterances={utterances} />
              </div>
            </CollapsibleCard>
          )}

          {/* Emotion Fusion Quality */}
          {data.emotionComparison && (
            <CollapsibleCard title="Emotion Fusion Quality" icon={<Activity className="w-4 h-4 text-cyan-400" />}
              defaultOpen={false}
              badge={
                <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                  data.emotionComparison.quality.acousticTextAgreementRate >= 70
                    ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500"
                }`}>
                  {data.emotionComparison.quality.acousticTextAgreementRate.toFixed(0)}% agree
                </span>
              }>
              <div className="space-y-2.5">
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: "Audio ↔ Text", value: data.emotionComparison.quality.acousticTextAgreementRate },
                    { label: "Fused → Audio", value: data.emotionComparison.quality.fusedMatchesAcousticRate },
                    { label: "Fused → Text", value: data.emotionComparison.quality.fusedMatchesTextRate },
                  ].map((m) => (
                    <div key={m.label} className="text-center">
                      <div className="text-[15px] font-bold" style={{ color: getScoreColor(m.value) }}>{m.value.toFixed(0)}%</div>
                      <div className="text-[9px] text-muted-foreground font-medium">{m.label}</div>
                    </div>
                  ))}
                </div>
                {data.emotionComparison.quality.disagreementCount > 0 && (
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <AlertCircle className="w-3 h-3 text-amber-500 shrink-0" />
                    <span className="text-muted-foreground">
                      {data.emotionComparison.quality.disagreementCount} utterance{data.emotionComparison.quality.disagreementCount !== 1 ? "s" : ""} with cross-modal mismatch
                    </span>
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground">{data.emotionComparison.totalUtterances} utterances analyzed</p>
              </div>
            </CollapsibleCard>
          )}

          {/* Policy Violations */}
          {policyViolations.length > 0 && (
            <CollapsibleCard title={`Policy Violations (${policyViolations.length})`}
              icon={<AlertTriangleIcon className="w-4 h-4 text-red-400" />}>
              <div className="space-y-3 max-h-[400px] overflow-y-auto pr-1">
                {policyViolations.map((v) => (
                  <div key={v.id} className="rounded-lg bg-red-500/5 border border-red-500/10 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-bold text-foreground">{v.policyTitle}</span>
                      <span className="text-[11px] font-bold text-red-400">{v.score}%</span>
                    </div>
                    <p className="text-[12px] text-muted-foreground leading-relaxed">{v.reasoning}</p>

                    {feedbackDone.has(v.id) ? (
                      <p className="text-[11px] text-emerald-500 font-semibold pt-2 border-t border-border/50">Feedback recorded</p>
                    ) : flaggedItems.has(v.id) ? (
                      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border/50">
                        <span className="text-[11px] text-muted-foreground">Accurate finding?</span>
                        <button type="button" onClick={() => submitFeedback(v.id)} className="text-[11px] font-bold text-emerald-500 hover:underline">Yes</button>
                        <button type="button" onClick={() => submitFeedback(v.id)} className="text-[11px] font-bold text-red-400 hover:underline">No</button>
                      </div>
                    ) : (
                      <div className="flex justify-end pt-2 border-t border-border/50">
                        <button type="button" onClick={() => toggleFlag(v.id)}
                          className="text-[11px] font-semibold text-muted-foreground hover:text-foreground flex items-center gap-1">
                          <Flag className="w-3 h-3" /> Dispute
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CollapsibleCard>
          )}
        </div>
      </div>

      {/* ── Explainability Panel (full width) ────────────────────────────── */}
      {explainability && (
        <EvidenceAnchoredExplainabilityPanel explainability={explainability} onJumpTo={handleJumpTo} />
      )}
    </div>
  );
}
