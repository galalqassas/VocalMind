import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft, Play, Pause, SkipBack, SkipForward,
  Loader2, AlertTriangle, Target, Headphones, Volume2, VolumeX,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  getInteractionDetail, getAudioUrl,
  type InteractionDetail, type UtteranceData, type EmotionEventData,
} from "../../services/api";
import { EmotionComparisonPanel } from "../manager/EmotionComparisonPanel.tsx";
import { EvidenceAnchoredExplainabilityPanel } from "../manager/EvidenceAnchoredExplainabilityPanel";
import { AnalysisTabs } from "../manager/AnalysisTabs";
import { formatResponseTime } from "../../utils/interactionFormat";

// ── Constants ────────────────────────────────────────────────────────────────

const EMOTION_SCORE: Record<string, number> = {
  angry: 0, frustrated: 1, fearful: 1.5, sad: 2, neutral: 3, happy: 4,
};

const CANONICAL_EMOTIONS = new Set(["angry", "frustrated", "sad", "neutral", "happy"]);

function normalizeEmotion(raw: string): string {
  const lower = (raw || "").toLowerCase().trim();
  if (CANONICAL_EMOTIONS.has(lower)) return lower;
  const map: Record<string, string> = {
    fear: "frustrated", fearful: "frustrated", disgust: "angry",
    surprise: "happy", calm: "neutral", contempt: "angry",
  };
  return map[lower] || "neutral";
}

function buildEmotionChartData(utterances: UtteranceData[]) {
  return utterances.map((u, i) => ({
    index: i,
    time: u.timestamp,
    score: EMOTION_SCORE[normalizeEmotion(u.emotion)] ?? 3,
    emotion: normalizeEmotion(u.emotion),
    speaker: u.speaker,
  }));
}

// ── Component ────────────────────────────────────────────────────────────────

export function AgentCallDetail() {
  const { id } = useParams();
  const [data, setData] = useState<InteractionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // Audio state
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [audioEpoch, setAudioEpoch] = useState(0);

  const handleJumpTo = useCallback((seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      audioRef.current.play().catch(() => {});
    }
  }, []);

  useEffect(() => {
    if (!id) return;
    let isCancelled = false;

    getInteractionDetail(id)
      .then((baseDetail) => {
        if (!isCancelled) { setData(baseDetail); setLoading(false); }
        return getInteractionDetail(id, { includeLLMTriggers: true, skipCache: true })
          .then((d) => { if (!isCancelled) setData(d); })
          .catch(() => {});
      })
      .catch((err) => {
        if (!isCancelled) { setError(err.message); setLoading(false); }
      });

    return () => { isCancelled = true; };
  }, [id]);

  // Audio event handlers
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => setCurrentTime(el.currentTime);
    const onMeta = () => setDuration(el.duration);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("loadedmetadata", onMeta);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("loadedmetadata", onMeta);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
    };
  }, [audioEpoch]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <span className="ml-3 text-muted-foreground text-sm">Loading call details...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <AlertTriangle className="w-10 h-10 text-amber-500 mx-auto mb-3" />
          <p className="text-muted-foreground text-sm">Failed to load call details</p>
          <p className="text-muted-foreground/60 text-xs mt-1">{error}</p>
        </div>
      </div>
    );
  }

  const interaction = data.interaction;
  const utterances = data.utterances;
  const emotionEvents = data.emotionEvents;
  const policyViolations = data.policyViolations;

  const emotionTrigger = data?.emotionTriggers ?? data?.llmTriggers ?? null;
  const ragCompliance = data?.ragCompliance ?? null;
  const ragProcess = ragCompliance?.processAdherence ?? data?.llmTriggers?.processAdherence ?? null;
  const ragNli = ragCompliance?.nliPolicy ?? data?.llmTriggers?.nliPolicy ?? null;
  const explainability = emotionTrigger?.explainability ?? ragCompliance?.explainability ?? data?.llmTriggers?.explainability ?? null;

  const hasAnalysisData = !!(
    emotionTrigger?.emotionShift || ragProcess || ragNli ||
    policyViolations.length > 0 || data?.emotionComparison || explainability
  );

  const chartData = buildEmotionChartData(utterances);

  const callData = {
    date: interaction.date,
    time: interaction.time,
    duration: interaction.duration,
    language: interaction.language,
    overallScore: interaction.overallScore,
    empathyScore: interaction.empathyScore,
    policyScore: interaction.policyScore,
    resolutionScore: interaction.resolutionScore,
    responseTime: formatResponseTime(interaction.responseTime),
  };

  const getScoreColor = (score: number) => {
    if (score >= 85) return "var(--success)";
    if (score >= 75) return "var(--primary)";
    return "var(--destructive)";
  };

  const getEmotionStyle = (emotion: string) => {
    const e = normalizeEmotion(emotion);
    switch (e) {
      case "happy": return { bg: "rgba(16, 185, 129, 0.1)", text: "var(--success)", label: "Happy" };
      case "angry": return { bg: "rgba(239, 68, 68, 0.1)", text: "var(--destructive)", label: "Angry" };
      case "frustrated": return { bg: "rgba(245, 158, 11, 0.1)", text: "#D97706", label: "Frustrated" };
      case "sad": return { bg: "rgba(99, 102, 241, 0.1)", text: "#6366F1", label: "Sad" };
      default: return { bg: "var(--muted)", text: "var(--muted-foreground)", label: "Neutral" };
    }
  };

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  return (
    <div className="p-6 space-y-5">
      {/* ── Back Nav ───────────────────────────────────────────────────── */}
      <Link to="/agent/calls" className="inline-flex items-center gap-2 text-[13px] font-semibold text-primary hover:underline">
        <ArrowLeft className="w-4 h-4" />
        Back to My Calls
      </Link>

      {/* ── Hero Card ─────────────────────────────────────────────────── */}
      <div className="bg-card rounded-2xl border border-border p-5">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-1">Call Review</div>
            <h2 className="text-xl font-bold text-foreground">{callData.date} · {callData.time}</h2>
            <div className="text-[13px] text-muted-foreground mt-0.5">{callData.duration} · {callData.language}</div>
          </div>
          <div className="relative group" style={{ width: 80, height: 80 }}>
            <svg className="w-full h-full -rotate-90">
              <circle cx="40" cy="40" r="36" fill="none" stroke="var(--border)" strokeWidth="6" />
              <circle cx="40" cy="40" r="36" fill="none" stroke={getScoreColor(callData.overallScore)}
                strokeWidth="6" strokeLinecap="round"
                strokeDasharray={`${(callData.overallScore / 100) * 226.19} 226.19`} />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-lg font-bold" style={{ color: getScoreColor(callData.overallScore) }}>{callData.overallScore}%</span>
            </div>
            <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1.5 text-[10px] text-muted-foreground shadow-lg opacity-0 group-hover:opacity-100 transition-opacity">
              30% Empathy · 40% Policy · 30% Resolution
            </div>
          </div>
        </div>

        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Empathy", value: callData.empathyScore, color: "var(--primary)" },
            { label: "Policy", value: callData.policyScore, color: "var(--success)" },
            { label: "Resolution", value: callData.resolutionScore, color: "var(--foreground)" },
            { label: "Resp. Time", value: callData.responseTime, isText: true },
          ].map((s) => (
            <div key={s.label} className="rounded-lg bg-muted/40 border border-border/50 px-3 py-2 text-center">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-0.5">{s.label}</div>
              <div className="text-base font-bold" style={{ color: s.isText ? "var(--foreground)" : getScoreColor(s.value as number) }}>
                {s.isText ? s.value : `${s.value}%`}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Audio Player ──────────────────────────────────────────────── */}
      {interaction.audioFilePath && (
        <div className="bg-card rounded-2xl border border-border p-4">
          <audio ref={audioRef} key={audioEpoch} src={getAudioUrl(interaction.id)} preload="metadata" className="hidden" />
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <button type="button" onClick={() => { if (audioRef.current) audioRef.current.currentTime = Math.max(0, currentTime - 5); }}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
                <SkipBack className="w-4 h-4" />
              </button>
              <button type="button"
                onClick={() => { const el = audioRef.current; if (el) isPlaying ? el.pause() : el.play().catch(() => {}); }}
                className="w-10 h-10 flex items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm">
                {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
              </button>
              <button type="button" onClick={() => { if (audioRef.current) audioRef.current.currentTime = Math.min(duration, currentTime + 5); }}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
                <SkipForward className="w-4 h-4" />
              </button>
            </div>
            <span className="text-[12px] font-mono text-muted-foreground w-[80px]">{fmtTime(currentTime)} / {fmtTime(duration)}</span>
            <div className="flex-1 h-1.5 rounded-full bg-muted cursor-pointer" onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const pct = (e.clientX - rect.left) / rect.width;
              if (audioRef.current) audioRef.current.currentTime = pct * duration;
            }}>
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: duration ? `${(currentTime / duration) * 100}%` : "0%" }} />
            </div>
            <button type="button" onClick={() => { if (audioRef.current) { audioRef.current.muted = !isMuted; setIsMuted(!isMuted); } }}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors">
              {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {/* ── Emotion Timeline ──────────────────────────────────────────── */}
      {chartData.length > 0 && (
        <div className="bg-card rounded-2xl border border-border p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[14px] font-bold text-foreground">Emotion Timeline</h3>
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-cyan-500" /> Customer</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" /> Agent</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "var(--muted-foreground)" }} />
              <YAxis domain={[0, 4]} ticks={[0, 1, 2, 3, 4]} tick={{ fontSize: 9, fill: "var(--muted-foreground)" }}
                tickFormatter={(v: number) => ["Angry", "Frus.", "Sad", "Neut.", "Happy"][v] || ""} />
              <RechartsTooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number) => [["Angry", "Frustrated", "Sad", "Neutral", "Happy"][v] || "?", "Emotion"]} />
              <ReferenceLine y={3} stroke="var(--border)" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="score" stroke="var(--primary)" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Main Content Grid ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        {/* ── Transcript (left) ────────────────────────────────────────── */}
        <div className="lg:col-span-7">
          <div className="bg-card rounded-2xl border border-border p-5">
            <h3 className="text-[14px] font-bold text-foreground mb-3">Transcript</h3>
            <div className="space-y-3 max-h-[600px] overflow-y-auto pr-1">
              {utterances.map((utterance) => {
                const isAgent = utterance.speaker === "agent";
                const emotionStyle = getEmotionStyle(utterance.emotion);
                return (
                  <div key={utterance.id} className={`flex gap-3 ${isAgent ? "" : "flex-row-reverse"}`}>
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                      isAgent ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                    }`}>{isAgent ? "A" : "C"}</div>
                    <div className={`flex-1 max-w-[80%] p-3 ${
                      isAgent ? "bg-success/10 rounded-[0_12px_12px_12px]" : "bg-muted/50 rounded-[12px_0_12px_12px]"
                    }`}>
                      <div className={`flex items-center gap-2 mb-1 ${isAgent ? "" : "flex-row-reverse"}`}>
                        <span className="text-[13px] font-semibold text-muted-foreground">{isAgent ? "Me" : "Customer"}</span>
                        <span className="text-[12px] text-muted-foreground/60">{utterance.timestamp}</span>
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold"
                          style={{ backgroundColor: emotionStyle.bg, color: emotionStyle.text }}>
                          {emotionStyle.label} {Math.round(utterance.confidence * 100)}%
                        </span>
                      </div>
                      <p className="text-[14px] text-foreground">{utterance.text}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Analysis Sidebar (right) ─────────────────────────────────── */}
        <div className="lg:col-span-5 space-y-3 lg:sticky lg:top-6 self-start">
          {!hasAnalysisData && emotionTrigger && !emotionTrigger.available ? (
            <div className="bg-card rounded-2xl border border-border p-5 text-center space-y-3">
              <p className="text-[13px] font-semibold text-foreground">LLM coaching insights unavailable.</p>
              {emotionTrigger.error && (
                <p className="text-[11px] text-muted-foreground">{emotionTrigger.error}</p>
              )}
            </div>
          ) : hasAnalysisData ? (
            <AnalysisTabs
              emotionTrigger={emotionTrigger}
              ragProcess={ragProcess}
              ragNli={ragNli}
              policyViolations={policyViolations}
              emotionComparison={data?.emotionComparison ?? null}
              utterances={utterances}
              onJumpTo={handleJumpTo}
              variant="agent"
            />
          ) : (
            <>
              {/* Coaching Points (kept for backward compat when no LLM data) */}
              {policyViolations.length > 0 && (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-2xl p-5">
                  <div className="flex items-center gap-2 mb-1">
                    <Target className="w-4 h-4 text-amber-500" />
                    <h3 className="text-[14px] font-semibold text-amber-500">Coaching Points</h3>
                  </div>
                  <p className="text-[11px] italic text-muted-foreground mb-3">Areas to focus on from saved findings.</p>
                  <div className="space-y-2.5">
                    {policyViolations.map((v) => (
                      <div key={v.id} className="bg-card border border-amber-500/20 rounded-xl p-3">
                        <h4 className="text-[13px] font-semibold text-foreground mb-1">{v.policyTitle}</h4>
                        <p className="text-[12px] text-muted-foreground mb-1">{v.reasoning}</p>
                        <span className="text-[12px] font-semibold text-amber-500">Score: {v.score}% · target 80%+</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Emotion Comparison Panel ──────────────────────────────────── */}
      {data.emotionComparison && (
        <EmotionComparisonPanel data={data.emotionComparison} />
      )}

      {/* ── Customer Emotion Journey ──────────────────────────────────── */}
      {emotionEvents.length > 0 && (
        <div className="bg-card rounded-2xl border border-border p-5">
          <h3 className="text-[14px] font-bold text-foreground mb-3">Customer Emotion Journey</h3>
          <div className="space-y-3">
            {emotionEvents.map((event) => {
              const fromStyle = getEmotionStyle(event.fromEmotion);
              const toStyle = getEmotionStyle(event.toEmotion);
              const isPositive = normalizeEmotion(event.toEmotion) === "happy";
              return (
                <div key={event.id} className={`border rounded-xl p-3.5 space-y-2.5 ${
                  isPositive ? "bg-success/5 border-success/30" : "bg-destructive/5 border-destructive/20"
                }`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-muted text-muted-foreground border border-border font-mono">{event.timestamp}</span>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold" style={{ backgroundColor: fromStyle.bg, color: fromStyle.text }}>{fromStyle.label}</span>
                      <span className="text-muted-foreground/60">→</span>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold" style={{ backgroundColor: toStyle.bg, color: toStyle.text }}>{toStyle.label}</span>
                    </div>
                    <button onClick={() => handleJumpTo(event.jumpToSeconds)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 text-primary border border-primary/30 rounded-lg text-[11px] font-bold hover:bg-primary/20 transition-all">
                      <Play className="w-3 h-3 fill-current" />
                      {event.timestamp}
                    </button>
                  </div>
                  <div className="bg-background border-l-4 border-success rounded p-2.5">
                    <p className="text-[12px] italic text-muted-foreground leading-relaxed">{event.justification}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Explainability Panel ──────────────────────────────────────── */}
      {explainability && (
        <EvidenceAnchoredExplainabilityPanel explainability={explainability} onJumpTo={handleJumpTo} />
      )}
    </div>
  );
}
