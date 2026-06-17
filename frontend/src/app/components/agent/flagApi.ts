/**
 * Tiny re-export shim so FlagButton can stay framework-free of the
 * services/ path conventions. Just thin wrappers — keeps imports tidy.
 */
import { disputeCompliance, disputeEmotionEvent } from "../../services/feedbackLoop";

export async function disputeEmotionFlag(eventId: string, note: string): Promise<void> {
  await disputeEmotionEvent(eventId, note || undefined);
}

export async function disputeComplianceFlag(complianceId: string, note: string): Promise<void> {
  await disputeCompliance(complianceId, note || undefined);
}
