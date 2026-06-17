import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  AlertCircle,
  Check,
  ClipboardCheck,
  ExternalLink,
  Loader2,
  MessageSquare,
  ShieldAlert,
  Smile,
  X,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import {
  getReviewQueue,
  reviewComplianceFlag,
  reviewEmotionFlag,
  type ComplianceFlagItem,
  type EmotionFlagItem,
  type ReviewQueue as ReviewQueueData,
} from "../../services/feedbackLoop";

const EMOTION_OPTIONS = ["neutral", "happy", "frustrated", "angry", "sad", "empathetic", "fearful"];

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function EmotionFlagCard({
  item,
  onResolved,
}: {
  item: EmotionFlagItem;
  onResolved: () => void;
}) {
  const [mode, setMode] = useState<"idle" | "accept" | "reject">("idle");
  const [correctedEmotion, setCorrectedEmotion] = useState(item.previous_emotion || "neutral");
  const [correctedJustification, setCorrectedJustification] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await reviewEmotionFlag(item.review_id, {
        decision: mode === "accept" ? "accept" : "reject",
        corrected_emotion: mode === "accept" ? correctedEmotion : undefined,
        corrected_justification: mode === "accept" ? correctedJustification || undefined : undefined,
        manager_note: note || undefined,
      });
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="border border-border rounded-xl p-5 bg-card space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-500/10 text-amber-600 flex items-center justify-center flex-shrink-0">
            <Smile className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <div className="text-[14px] font-semibold text-foreground">
              Emotion: <span className="text-amber-600">{item.new_emotion}</span>
              {item.previous_emotion && (
                <span className="text-muted-foreground font-normal text-[12px]"> (was {item.previous_emotion})</span>
              )}
            </div>
            <div className="text-[12px] text-muted-foreground">
              Flagged by <span className="font-medium text-foreground">{item.agent_name}</span>{" "}
              · {formatWhen(item.agent_flagged_at)}
            </div>
          </div>
        </div>
        <Link
          to={`/manager/inspector/${item.interaction_id}`}
          className="text-[12px] text-primary hover:underline inline-flex items-center gap-1"
        >
          Open call <ExternalLink className="w-3 h-3" />
        </Link>
      </div>

      {item.llm_justification && (
        <div className="text-[12.5px] text-muted-foreground bg-muted/40 rounded-md p-2.5">
          <span className="font-semibold text-foreground">AI justification:</span> {item.llm_justification}
          {item.confidence_score != null && (
            <Badge variant="secondary" className="ml-2 text-[10px]">
              conf {(item.confidence_score * 100).toFixed(0)}%
            </Badge>
          )}
        </div>
      )}

      {item.agent_flag_note && (
        <div className="text-[12.5px] bg-amber-500/5 border border-amber-500/20 rounded-md p-2.5 flex items-start gap-2">
          <MessageSquare className="w-3.5 h-3.5 text-amber-600 mt-0.5 flex-shrink-0" />
          <span><span className="font-semibold">Agent says:</span> {item.agent_flag_note}</span>
        </div>
      )}

      {mode === "idle" ? (
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={() => setMode("accept")} className="bg-emerald-600 hover:bg-emerald-700">
            <Check className="w-3.5 h-3.5 mr-1" /> Accept flag
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode("reject")}>
            <X className="w-3.5 h-3.5 mr-1" /> Reject
          </Button>
        </div>
      ) : (
        <div className="space-y-3 pt-1 border-t border-border/60">
          {mode === "accept" && (
            <>
              <div>
                <Label className="text-[11px]">Corrected emotion</Label>
                <select
                  value={correctedEmotion}
                  onChange={(e) => setCorrectedEmotion(e.target.value)}
                  className="w-full mt-1 h-9 px-2 rounded-md border border-border bg-background text-[13px]"
                >
                  {EMOTION_OPTIONS.map((e) => (
                    <option key={e} value={e}>{e}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label className="text-[11px]">Corrected justification (optional)</Label>
                <Textarea
                  value={correctedJustification}
                  onChange={(e) => setCorrectedJustification(e.target.value)}
                  rows={2}
                  placeholder="Why this emotion better fits the moment"
                />
              </div>
            </>
          )}
          <div>
            <Label className="text-[11px]">Note to agent (optional)</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Short explanation" />
          </div>
          {error && <div className="text-[12px] text-destructive">{error}</div>}
          <div className="flex gap-2">
            <Button size="sm" disabled={submitting} onClick={submit}>
              {submitting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
              Confirm {mode}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("idle")} disabled={submitting}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ComplianceFlagCard({
  item,
  onResolved,
}: {
  item: ComplianceFlagItem;
  onResolved: () => void;
}) {
  const [mode, setMode] = useState<"idle" | "accept" | "reject">("idle");
  const [correctedIsCompliant, setCorrectedIsCompliant] = useState(!item.is_compliant);
  const [correctedScore, setCorrectedScore] = useState<string>("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await reviewComplianceFlag(item.review_id, {
        decision: mode === "accept" ? "accept" : "reject",
        corrected_is_compliant: mode === "accept" ? correctedIsCompliant : undefined,
        corrected_score: mode === "accept" && correctedScore ? Number(correctedScore) : undefined,
        manager_note: note || undefined,
      });
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="border border-border rounded-xl p-5 bg-card space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-rose-500/10 text-rose-600 flex items-center justify-center flex-shrink-0">
            <ShieldAlert className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <div className="text-[14px] font-semibold text-foreground">
              {item.policy_title || "Policy"}{" "}
              <span className={`text-[12px] ${item.is_compliant ? "text-emerald-600" : "text-rose-600"}`}>
                · AI verdict: {item.is_compliant ? "compliant" : "non-compliant"}
              </span>
            </div>
            <div className="text-[12px] text-muted-foreground">
              Flagged by <span className="font-medium text-foreground">{item.agent_name}</span>{" "}
              · {formatWhen(item.agent_flagged_at)}
            </div>
          </div>
        </div>
        <Link
          to={`/manager/inspector/${item.interaction_id}`}
          className="text-[12px] text-primary hover:underline inline-flex items-center gap-1"
        >
          Open call <ExternalLink className="w-3 h-3" />
        </Link>
      </div>

      {item.llm_reasoning && (
        <div className="text-[12.5px] text-muted-foreground bg-muted/40 rounded-md p-2.5">
          <span className="font-semibold text-foreground">AI reasoning:</span> {item.llm_reasoning}
          <Badge variant="secondary" className="ml-2 text-[10px]">
            score {(item.compliance_score * 100).toFixed(0)}%
          </Badge>
        </div>
      )}

      {item.agent_flag_note && (
        <div className="text-[12.5px] bg-rose-500/5 border border-rose-500/20 rounded-md p-2.5 flex items-start gap-2">
          <MessageSquare className="w-3.5 h-3.5 text-rose-600 mt-0.5 flex-shrink-0" />
          <span><span className="font-semibold">Agent says:</span> {item.agent_flag_note}</span>
        </div>
      )}

      {mode === "idle" ? (
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={() => setMode("accept")} className="bg-emerald-600 hover:bg-emerald-700">
            <Check className="w-3.5 h-3.5 mr-1" /> Accept flag
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode("reject")}>
            <X className="w-3.5 h-3.5 mr-1" /> Reject
          </Button>
        </div>
      ) : (
        <div className="space-y-3 pt-1 border-t border-border/60">
          {mode === "accept" && (
            <>
              <div className="flex items-center gap-3">
                <Label className="text-[11px]">Corrected verdict</Label>
                <select
                  value={correctedIsCompliant ? "yes" : "no"}
                  onChange={(e) => setCorrectedIsCompliant(e.target.value === "yes")}
                  className="h-9 px-2 rounded-md border border-border bg-background text-[13px]"
                >
                  <option value="yes">Compliant</option>
                  <option value="no">Non-compliant</option>
                </select>
              </div>
              <div>
                <Label className="text-[11px]">Corrected score 0–1 (optional)</Label>
                <Input
                  value={correctedScore}
                  onChange={(e) => setCorrectedScore(e.target.value)}
                  placeholder="0.85"
                  inputMode="decimal"
                />
              </div>
            </>
          )}
          <div>
            <Label className="text-[11px]">Note to agent (optional)</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Short explanation" />
          </div>
          {error && <div className="text-[12px] text-destructive">{error}</div>}
          <div className="flex gap-2">
            <Button size="sm" disabled={submitting} onClick={submit}>
              {submitting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
              Confirm {mode}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMode("idle")} disabled={submitting}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ReviewQueue() {
  const [data, setData] = useState<ReviewQueueData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getReviewQueue());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review queue");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const totalCount = useMemo(
    () => (data ? data.emotion.length + data.compliance.length : 0),
    [data],
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-primary" />
            <h2 className="text-[18px] font-bold text-foreground">Review Queue</h2>
          </div>
          <p className="text-[13px] text-muted-foreground mt-1">
            Agents have flagged these AI evaluations. Accept to record a correction, reject to keep the AI verdict.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-10 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Loading…
        </div>
      )}

      {error && (
        <div className="border border-destructive/30 bg-destructive/5 text-destructive text-[13px] rounded-md p-3 flex items-center gap-2">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {!loading && !error && data && (
        <Tabs defaultValue="all" className="space-y-4">
          <TabsList>
            <TabsTrigger value="all">All <Badge variant="secondary" className="ml-1.5">{totalCount}</Badge></TabsTrigger>
            <TabsTrigger value="emotion">Emotion <Badge variant="secondary" className="ml-1.5">{data.emotion.length}</Badge></TabsTrigger>
            <TabsTrigger value="compliance">Compliance <Badge variant="secondary" className="ml-1.5">{data.compliance.length}</Badge></TabsTrigger>
          </TabsList>

          <TabsContent value="all" className="space-y-3">
            {totalCount === 0 ? (
              <div className="text-center text-sm text-muted-foreground py-10">Queue is clear.</div>
            ) : (
              <>
                {data.emotion.map((item) => (
                  <EmotionFlagCard key={item.review_id} item={item} onResolved={refresh} />
                ))}
                {data.compliance.map((item) => (
                  <ComplianceFlagCard key={item.review_id} item={item} onResolved={refresh} />
                ))}
              </>
            )}
          </TabsContent>

          <TabsContent value="emotion" className="space-y-3">
            {data.emotion.length === 0 ? (
              <div className="text-center text-sm text-muted-foreground py-10">No emotion flags pending.</div>
            ) : (
              data.emotion.map((item) => (
                <EmotionFlagCard key={item.review_id} item={item} onResolved={refresh} />
              ))
            )}
          </TabsContent>

          <TabsContent value="compliance" className="space-y-3">
            {data.compliance.length === 0 ? (
              <div className="text-center text-sm text-muted-foreground py-10">No compliance flags pending.</div>
            ) : (
              data.compliance.map((item) => (
                <ComplianceFlagCard key={item.review_id} item={item} onResolved={refresh} />
              ))
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
