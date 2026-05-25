import { useState } from "react";
import {
  Brain, Shield, FileWarning, Activity, Info, AlertCircle,
  XCircle, BookOpen, Flag, AlertTriangle as AlertTriangleIcon,
} from "lucide-react";
import type {
  EmotionTriggerReport, LLMProcessAdherence, LLMNliPolicy,
  UtteranceData, EmotionComparison, PolicyViolationData,
} from "../../services/api";

/* ── Helpers ──────────────────────────────────────────────────────────── */

function getScoreColor(score: number) {
  if (score >= 85) return "var(--success)";
  if (score >= 70) return "var(--primary)";
  if (score >= 50) return "var(--warning, #F59E0B)";
  return "var(--destructive)";
}

function formatAlignmentPercent(score: number): { value: number; label: string } {
  const normalized = score <= 1 ? score * 100 : score;
  const pct = Math.round(Math.max(0, Math.min(100, normalized)));
  return { value: pct, label: `${pct}%` };
}

function formatPolicyEffective(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}

function formatPolicyVersion(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const uuidLike = /^[0-9a-f-]{32,}/i;
  if (uuidLike.test(trimmed.split(":")[0] ?? trimmed)) {
    const [head, tail] = trimmed.split(":", 2);
    const shortHead = head.slice(0, 8);
    return tail ? `${shortHead}…@${tail}` : `${shortHead}…`;
  }
  return trimmed;
}

function ConfidenceBadge({ score }: { score?: number | null }) {
  if (score == null) return null;
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-muted-foreground">
      Confidence {pct}%
    </span>
  );
}

function InsufficientEvidenceWarning({ flag }: { flag?: boolean }) {
  if (!flag) return null;
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 flex items-center gap-2">
      <AlertCircle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
      <p className="text-[11px] text-amber-600 dark:text-amber-400 font-medium">
        Insufficient evidence &mdash; results may be unreliable.
      </p>
    </div>
  );
}

function EvidenceQuotes({ quotes }: { quotes?: string[] }) {
  if (!quotes?.length) return null;
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Evidence ({quotes.length})</p>
      {quotes.map((q, i) => (
        <p key={i} className="text-[12px] text-foreground/80 italic border-l-2 border-border pl-2 leading-relaxed">&ldquo;{q}&rdquo;</p>
      ))}
    </div>
  );
}

function CitationsList({ citations, onJumpTo, utterances }: {
  citations?: Array<{ source?: string; speaker?: string; quote?: string; utteranceIndex?: number | null }>;
  onJumpTo: (s: number) => void;
  utterances: UtteranceData[];
}) {
  if (!citations?.length) return null;
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Citations ({citations.length})</p>
      {citations.map((c, i) => {
        const utt = c.utteranceIndex != null ? utterances[c.utteranceIndex] : null;
        return (
          <div key={i} className="rounded-lg bg-muted/30 border border-border/40 p-2 text-[11px] space-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-muted-foreground">{c.source}{c.speaker ? ` · ${c.speaker}` : ""}</span>
              {utt && (
                <button type="button" onClick={() => onJumpTo(utt.startTime)}
                  className="text-[10px] font-bold text-primary hover:underline">{utt.timestamp}</button>
              )}
            </div>
            {c.quote && <p className="text-foreground/70 italic leading-relaxed">&ldquo;{c.quote}&rdquo;</p>}
          </div>
        );
      })}
    </div>
  );
}

function EfficiencyGauge({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 10));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">Efficiency</span>
        <span className="text-[12px] font-bold" style={{ color: getScoreColor(pct) }}>{score}/10</span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: getScoreColor(pct) }} />
      </div>
    </div>
  );
}

/* ── Types ─────────────────────────────────────────────────────────────── */

interface AnalysisTabsProps {
  emotionTrigger: EmotionTriggerReport | null;
  ragProcess: LLMProcessAdherence | null;
  ragNli: LLMNliPolicy | null;
  policyViolations: PolicyViolationData[];
  emotionComparison: EmotionComparison | null;
  utterances: UtteranceData[];
  onJumpTo: (seconds: number) => void;
  variant?: "manager" | "agent";
  /* feedback / flag callbacks (manager only) */
  flaggedItems?: Set<string>;
  feedbackDone?: Set<string>;
  onToggleFlag?: (id: string) => void;
  onSubmitFeedback?: (id: string) => void;
}

/* ── Soft labels for agent variant ─────────────────────────────────── */

const LABELS = {
  manager: { emotion: "Emotion Analysis", process: "Process Adherence", policy: "Policy Inference (NLI)", quality: "Emotion Fusion Quality", violations: "Policy Violations", missing: "Missing SOP Steps" },
  agent:   { emotion: "Emotion Feedback", process: "Call Flow Check", policy: "Policy Consistency", quality: "Signal Quality", violations: "Coaching Points", missing: "Steps to Improve" },
};

/* ── Component ─────────────────────────────────────────────────────── */

export function AnalysisTabs({
  emotionTrigger, ragProcess, ragNli, policyViolations,
  emotionComparison, utterances, onJumpTo,
  variant = "manager",
  flaggedItems, feedbackDone, onToggleFlag, onSubmitFeedback,
}: AnalysisTabsProps) {
  const [tab, setTab] = useState("emotion");
  const L = LABELS[variant];

  const tabs = [
    { id: "emotion", label: "Emotion", Icon: Brain, has: !!emotionTrigger?.emotionShift },
    { id: "process", label: "Process", Icon: Shield, has: !!ragProcess },
    { id: "policy", label: "Policy", Icon: FileWarning, has: !!ragNli || policyViolations.length > 0 },
    { id: "quality", label: "Quality", Icon: Activity, has: !!emotionComparison },
  ] as const;

  return (
    <>
      {/* Tab Bar */}
      <div className="flex bg-muted/20 rounded-xl border border-border p-1 gap-0.5">
        {tabs.map((t) => (
          <button key={t.id} type="button"
            onClick={() => t.has && setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-2.5 rounded-lg text-[11px] font-bold transition-all ${
              tab === t.id
                ? "bg-card text-foreground shadow-sm border border-border/60"
                : t.has ? "text-muted-foreground hover:text-foreground hover:bg-card/50" : "text-muted-foreground/30 cursor-default"
            }`}>
            <t.Icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="bg-card rounded-xl border border-border overflow-hidden">

        {/* ── Emotion ─────────────────────────────── */}
        {tab === "emotion" && (emotionTrigger?.emotionShift ? (
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-400" />
                <span className="text-[13px] font-bold text-foreground">{L.emotion}</span>
              </div>
              <div className="flex items-center gap-2">
                <ConfidenceBadge score={emotionTrigger.emotionShift.confidenceScore} />
                <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                  emotionTrigger.emotionShift.isDissonanceDetected ? "bg-amber-500/10 text-amber-500" : "bg-emerald-500/10 text-emerald-500"
                }`}>
                  {emotionTrigger.emotionShift.isDissonanceDetected ? "Dissonance" : "Aligned"}
                </span>
              </div>
            </div>
            <InsufficientEvidenceWarning flag={emotionTrigger.emotionShift.insufficientEvidence} />
            {emotionTrigger.emotionShift.currentCustomerEmotion && (
              <div className="rounded-lg bg-primary/5 border border-primary/10 p-2.5">
                <div className="flex items-center gap-1.5 mb-1">
                  <Info className="w-3 h-3 text-primary" />
                  <span className="text-[10px] font-semibold text-primary uppercase tracking-wider">Customer Emotion</span>
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
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  {variant === "agent" ? "What could help next time" : "Counterfactual"}
                </p>
                <p className="text-[12px] text-foreground italic leading-relaxed">{emotionTrigger.emotionShift.counterfactualCorrection}</p>
              </div>
            )}
            <EvidenceQuotes quotes={emotionTrigger.emotionShift.evidenceQuotes} />
            <CitationsList citations={emotionTrigger.emotionShift.citations} onJumpTo={onJumpTo} utterances={utterances} />
            {emotionTrigger.derived && (
              <div className="rounded-lg bg-muted/20 border border-border/40 p-2.5 space-y-2">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Derived Signals</p>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  <div><span className="text-muted-foreground">Acoustic:</span><span className="ml-1 font-semibold text-foreground capitalize">{emotionTrigger.derived.acousticEmotion || "—"}</span></div>
                  <div><span className="text-muted-foreground">Fused:</span><span className="ml-1 font-semibold text-foreground capitalize">{emotionTrigger.derived.fusedEmotion || "—"}</span></div>
                </div>
                {emotionTrigger.derived.customerText && (
                  <div className="space-y-0.5">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Latest Customer Turn</span>
                    <p className="text-[11px] italic text-foreground/80 leading-snug">&ldquo;{emotionTrigger.derived.customerText}&rdquo;</p>
                  </div>
                )}
                {emotionTrigger.derived.agentStatement && (
                  <div className="space-y-0.5">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Agent Response</span>
                    <p className="text-[11px] italic text-foreground/80 leading-snug">&ldquo;{emotionTrigger.derived.agentStatement}&rdquo;</p>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : <div className="p-8 text-center text-[12px] text-muted-foreground">No emotion data yet.</div>)}

        {/* ── Process ─────────────────────────────── */}
        {tab === "process" && (ragProcess ? (
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-blue-400" />
                <span className="text-[13px] font-bold text-foreground">{L.process}</span>
              </div>
              <div className="flex items-center gap-2">
                <ConfidenceBadge score={ragProcess.confidenceScore} />
                <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                  ragProcess.isResolved ? "bg-emerald-500/10 text-emerald-500" : "bg-red-500/10 text-red-500"
                }`}>
                  {ragProcess.isResolved ? "Resolved" : "Needs follow-up"}
                </span>
              </div>
            </div>
            <InsufficientEvidenceWarning flag={ragProcess.insufficientEvidence} />
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground">Topic:</span>
              <span className="text-[11px] font-semibold text-foreground">{ragProcess.detectedTopic}</span>
            </div>
            <EfficiencyGauge score={ragProcess.efficiencyScore} />
            <p className="text-[12px] text-muted-foreground leading-relaxed">{ragProcess.justification}</p>
            {ragProcess.missingSopSteps.length > 0 && (
              <div className={`rounded-lg p-2.5 ${variant === "agent" ? "bg-amber-500/5 border border-amber-500/10" : "bg-red-500/5 border border-red-500/10"}`}>
                <p className={`text-[10px] font-semibold uppercase tracking-wider mb-1 ${variant === "agent" ? "text-amber-500" : "text-red-400"}`}>{L.missing}</p>
                <ul className="space-y-1">
                  {ragProcess.missingSopSteps.map((step, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[12px] text-muted-foreground">
                      <XCircle className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${variant === "agent" ? "text-amber-500" : "text-red-400"}`} />
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <EvidenceQuotes quotes={ragProcess.evidenceQuotes} />
            <CitationsList citations={ragProcess.citations} onJumpTo={onJumpTo} utterances={utterances} />
          </div>
        ) : <div className="p-8 text-center text-[12px] text-muted-foreground">No process data yet.</div>)}

        {/* ── Policy ──────────────────────────────── */}
        {tab === "policy" && (
          <div className="p-4 space-y-4">
            {ragNli && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileWarning className="w-4 h-4 text-teal-400" />
                    <span className="text-[13px] font-bold text-foreground">{L.policy}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <ConfidenceBadge score={ragNli.confidenceScore} />
                    <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                      ragNli.nliCategory === "Entailment" ? "bg-emerald-500/10 text-emerald-500"
                        : ragNli.nliCategory === "Contradiction" ? "bg-red-500/10 text-red-500"
                          : "bg-amber-500/10 text-amber-500"
                    }`}>{ragNli.nliCategory}</span>
                  </div>
                </div>
                <InsufficientEvidenceWarning flag={ragNli.insufficientEvidence} />
                {(ragNli.policyVersion || ragNli.policyCategory || ragNli.policyEffectiveAt) && (
                  <div className="rounded-lg bg-muted/30 border border-border/50 p-2.5 space-y-1">
                    <div className="flex items-center gap-1.5 mb-1">
                      <BookOpen className="w-3 h-3 text-teal-400" />
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Policy Metadata</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                      {formatPolicyVersion(ragNli.policyVersion) && (
                        <>
                          <span className="text-muted-foreground">Version:</span>
                          <span className="font-semibold text-foreground" title={ragNli.policyVersion ?? undefined}>
                            {formatPolicyVersion(ragNli.policyVersion)}
                          </span>
                        </>
                      )}
                      {ragNli.policyCategory && (<><span className="text-muted-foreground">Category:</span><span className="font-semibold text-foreground">{ragNli.policyCategory}</span></>)}
                      {formatPolicyEffective(ragNli.policyEffectiveAt) && (
                        <>
                          <span className="text-muted-foreground">Effective:</span>
                          <span className="font-semibold text-foreground" title={ragNli.policyEffectiveAt ?? undefined}>
                            {formatPolicyEffective(ragNli.policyEffectiveAt)}
                          </span>
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
                {ragNli.policyAlignmentScore != null && (() => {
                  const alignment = formatAlignmentPercent(ragNli.policyAlignmentScore);
                  return (
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-muted-foreground">Alignment:</span>
                      <span className="text-[12px] font-bold" style={{ color: getScoreColor(alignment.value) }}>
                        {alignment.label}
                      </span>
                    </div>
                  );
                })()}
                <EvidenceQuotes quotes={ragNli.evidenceQuotes} />
                <CitationsList citations={ragNli.citations} onJumpTo={onJumpTo} utterances={utterances} />
              </div>
            )}
            {policyViolations.length > 0 && (
              <div className="space-y-2.5">
                {ragNli && <div className="h-px bg-border" />}
                <div className="flex items-center gap-2">
                  <AlertTriangleIcon className={`w-4 h-4 ${variant === "agent" ? "text-amber-500" : "text-red-400"}`} />
                  <span className="text-[13px] font-bold text-foreground">{L.violations} ({policyViolations.length})</span>
                </div>
                <div className="space-y-2.5 max-h-[350px] overflow-y-auto pr-1">
                  {policyViolations.map((v) => (
                    <div key={v.id} className={`rounded-lg p-3 space-y-2 ${variant === "agent" ? "bg-amber-500/5 border border-amber-500/10" : "bg-red-500/5 border border-red-500/10"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-bold text-foreground">{v.policyTitle}</span>
                        <span className={`text-[11px] font-bold ${variant === "agent" ? "text-amber-500" : "text-red-400"}`}>{v.score}%</span>
                      </div>
                      <p className="text-[12px] text-muted-foreground leading-relaxed">{v.reasoning}</p>
                      {variant === "manager" && onToggleFlag && onSubmitFeedback && (
                        <>
                          {feedbackDone?.has(v.id) ? (
                            <p className="text-[11px] text-emerald-500 font-semibold pt-2 border-t border-border/50">Feedback recorded</p>
                          ) : flaggedItems?.has(v.id) ? (
                            <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border/50">
                              <span className="text-[11px] text-muted-foreground">Accurate?</span>
                              <button type="button" onClick={() => onSubmitFeedback(v.id)} className="text-[11px] font-bold text-emerald-500 hover:underline">Yes</button>
                              <button type="button" onClick={() => onSubmitFeedback(v.id)} className="text-[11px] font-bold text-red-400 hover:underline">No</button>
                            </div>
                          ) : (
                            <div className="flex justify-end pt-2 border-t border-border/50">
                              <button type="button" onClick={() => onToggleFlag(v.id)}
                                className="text-[11px] font-semibold text-muted-foreground hover:text-foreground flex items-center gap-1">
                                <Flag className="w-3 h-3" /> Dispute
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!ragNli && policyViolations.length === 0 && (
              <div className="p-8 text-center text-[12px] text-muted-foreground">No policy data yet.</div>
            )}
          </div>
        )}

        {/* ── Quality ─────────────────────────────── */}
        {tab === "quality" && (emotionComparison ? (
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-cyan-400" />
                <span className="text-[13px] font-bold text-foreground">{L.quality}</span>
              </div>
              <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${
                emotionComparison.quality.acousticTextAgreementRate >= 70 ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500"
              }`}>{emotionComparison.quality.acousticTextAgreementRate.toFixed(0)}% agree</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "Audio ↔ Text", value: emotionComparison.quality.acousticTextAgreementRate },
                { label: "Fused → Audio", value: emotionComparison.quality.fusedMatchesAcousticRate },
                { label: "Fused → Text", value: emotionComparison.quality.fusedMatchesTextRate },
              ].map((m) => (
                <div key={m.label} className="text-center">
                  <div className="text-[15px] font-bold" style={{ color: getScoreColor(m.value) }}>{m.value.toFixed(0)}%</div>
                  <div className="text-[9px] text-muted-foreground font-medium">{m.label}</div>
                </div>
              ))}
            </div>
            {emotionComparison.quality.disagreementCount > 0 && (
              <div className="flex items-center gap-1.5 text-[11px]">
                <AlertCircle className="w-3 h-3 text-amber-500 shrink-0" />
                <span className="text-muted-foreground">
                  {emotionComparison.quality.disagreementCount} mismatch{emotionComparison.quality.disagreementCount !== 1 ? "es" : ""}
                </span>
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">{emotionComparison.totalUtterances} utterances analyzed</p>
          </div>
        ) : <div className="p-8 text-center text-[12px] text-muted-foreground">No quality data yet.</div>)}
      </div>
    </>
  );
}
