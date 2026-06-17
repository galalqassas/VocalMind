import { useState } from "react";
import { Flag, Loader2 } from "lucide-react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import {
  disputeComplianceFlag as disputeCompliance,
  disputeEmotionFlag as disputeEmotion,
} from "./flagApi";

type Kind = "emotion" | "compliance";

interface FlagButtonProps {
  kind: Kind;
  targetId: string;
  initialFlagged?: boolean;
}

export function FlagButton({ kind, targetId, initialFlagged = false }: FlagButtonProps) {
  const [flagged, setFlagged] = useState(initialFlagged);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (kind === "emotion") await disputeEmotion(targetId, note);
      else await disputeCompliance(targetId, note);
      setFlagged(true);
      setOpen(false);
      setNote("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to flag");
    } finally {
      setSubmitting(false);
    }
  };

  if (flagged) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-600 border border-amber-500/30">
        <Flag className="w-3 h-3" /> Flag pending review
      </span>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-muted/60 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        aria-label="Flag this AI evaluation as incorrect"
      >
        <Flag className="w-3 h-3" /> Flag as incorrect
      </button>
    );
  }

  return (
    <div className="mt-2 p-2.5 rounded-lg border border-border bg-background space-y-2">
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        placeholder="Why is this wrong? (your manager sees this)"
        className="text-[12px]"
      />
      {error && <div className="text-[11px] text-destructive">{error}</div>}
      <div className="flex gap-2">
        <Button size="sm" disabled={submitting} onClick={submit}>
          {submitting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
          Submit flag
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
