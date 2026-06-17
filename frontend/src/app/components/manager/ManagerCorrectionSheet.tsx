import { useState } from "react";
import { Loader2, Pencil } from "lucide-react";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "../ui/sheet";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { correctCompliance, correctEmotion } from "../../services/feedbackLoop";

const EMOTION_OPTIONS = ["neutral", "happy", "frustrated", "angry", "sad", "empathetic", "fearful"];

interface EmotionCorrectionProps {
  kind: "emotion";
  emotionEventId: string;
  currentEmotion?: string;
  currentJustification?: string | null;
}

interface ComplianceCorrectionProps {
  kind: "compliance";
  policyComplianceId: string;
  currentIsCompliant: boolean;
  currentScore?: number;
}

type Props = (EmotionCorrectionProps | ComplianceCorrectionProps) & {
  triggerLabel?: string;
  onSaved?: () => void;
};

export function ManagerCorrectionSheet(props: Props) {
  const [open, setOpen] = useState(false);

  // Shared form state
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Emotion-mode state
  const [correctedEmotion, setCorrectedEmotion] = useState(
    props.kind === "emotion" ? props.currentEmotion || "neutral" : "neutral",
  );
  const [correctedJustification, setCorrectedJustification] = useState(
    props.kind === "emotion" ? props.currentJustification ?? "" : "",
  );

  // Compliance-mode state
  const [correctedIsCompliant, setCorrectedIsCompliant] = useState(
    props.kind === "compliance" ? !props.currentIsCompliant : true,
  );
  const [correctedScore, setCorrectedScore] = useState<string>(
    props.kind === "compliance" && props.currentScore != null ? String(props.currentScore) : "",
  );

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (props.kind === "emotion") {
        await correctEmotion({
          emotion_event_id: props.emotionEventId,
          corrected_emotion: correctedEmotion,
          corrected_justification: correctedJustification || undefined,
          correction_reason: reason || undefined,
        });
      } else {
        await correctCompliance({
          policy_compliance_id: props.policyComplianceId,
          corrected_is_compliant: correctedIsCompliant,
          corrected_score: correctedScore ? Number(correctedScore) : undefined,
          correction_reason: reason || undefined,
        });
      }
      setOpen(false);
      props.onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save correction");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold text-primary bg-primary/10 hover:bg-primary/15 border border-primary/20 transition-colors"
        >
          <Pencil className="w-3 h-3" /> {props.triggerLabel ?? "Correct"}
        </button>
      </SheetTrigger>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>
            {props.kind === "emotion" ? "Correct emotion verdict" : "Correct compliance verdict"}
          </SheetTitle>
          <SheetDescription>
            Your correction is logged as feedback and used to refine the model.
          </SheetDescription>
        </SheetHeader>

        <div className="px-4 py-4 space-y-4">
          {props.kind === "emotion" ? (
            <>
              <div>
                <Label className="text-[11px]">Corrected emotion</Label>
                <select
                  value={correctedEmotion}
                  onChange={(e) => setCorrectedEmotion(e.target.value)}
                  className="w-full mt-1 h-9 px-2 rounded-md border border-border bg-background text-[13px]"
                >
                  {EMOTION_OPTIONS.map((emo) => (
                    <option key={emo} value={emo}>{emo}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label className="text-[11px]">Corrected justification (optional)</Label>
                <Textarea
                  value={correctedJustification}
                  onChange={(e) => setCorrectedJustification(e.target.value)}
                  rows={3}
                  placeholder="Why this emotion better fits the moment"
                />
              </div>
            </>
          ) : (
            <>
              <div>
                <Label className="text-[11px]">Corrected verdict</Label>
                <select
                  value={correctedIsCompliant ? "yes" : "no"}
                  onChange={(e) => setCorrectedIsCompliant(e.target.value === "yes")}
                  className="w-full mt-1 h-9 px-2 rounded-md border border-border bg-background text-[13px]"
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
            <Label className="text-[11px]">Reason / coaching note (optional)</Label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Visible to the agent and recorded with the feedback."
            />
          </div>
          {error && <div className="text-[12px] text-destructive">{error}</div>}
        </div>

        <SheetFooter>
          <Button onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
            Save correction
          </Button>
          <SheetClose asChild>
            <Button variant="ghost" disabled={submitting}>Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
