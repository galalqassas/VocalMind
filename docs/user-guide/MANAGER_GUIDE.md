# VocalMind Manager Guide & Manual

This guide describes the workflow, KPIs, and tool features available to users with the **Manager** role in the VocalMind platform.

---

## 1. Manager Dashboard & KPIs

Upon logging in, managers see the main dashboard, which rolls up performance metrics across the entire organization:

*   **Empathy Score**: Measures acoustic emotion trends and agent empathy during calls.
*   **Policy Compliance**: Percentage of calls conforming to active organization compliance rules.
*   **Resolution Score**: Success rate of agents resolving customer issues.
*   **Overall Score**: Weighted average of all metrics.
*   **Leaderboard**: Ranks agents (both human and AI) by their overall performance, highlighting top performers and coaching opportunities.

> [!NOTE]
> The dashboard stats employ a **5-minute TTL cache** server-side. Seeding new calls or reprocessing interactions will not update the dashboard metrics immediately until the cache expires.

---

## 2. Session Inspector (Call Search)

The **Session Inspector** is the primary search portal for call recordings:
*   **Filters**: Filter calls by Agent, Topic, Score Range, and status (`completed`, `pending`, `processing`, `failed`).
*   **Reprocess Action**: Reruns the entire audio processing pipeline for a call. Use this after uploading new SOP files or editing active policies to update scores.

---

## 3. Session Detail & Explainability Panel

Clicking a call opens the **Session Detail** view. This interface houses the core evaluation tools:

### 3.1 Diarized Transcript
*   Divides conversation turns between the **Agent** and **Customer**.
*   Utterances are synced with the audio player. Clicking a transcript segment jumps the audio playhead directly to that second.

### 3.2 Evidence Cards
The **Evidence-Anchored Explainability** panel bridges verdicts to actual call context:
*   **Trigger Attributions**: Amber warning cards highlighting specific triggers (e.g. *Sarcasm Detected*, *SOP Step Missed*) linked to precise transcript lines.
*   **Retrieval Provenance**: Blue cards linking RAG compliance verdicts to the source policy document, H1/H2 header section, and matching text chunk. Surfaces similarity scores.
*   **Interactive Jump**: Clicking the jump-to-timestamp icon on any card scrolls the transcript, highlights the turn, and seeks the audio.

---

## 4. AI Manager Assistant

The **Assistant** page provides a secure, natural-language-to-SQL interface:
*   **Example Queries**: Type queries like *"Show me Daniel's average score this week"* or *"List calls with hold time violations"*.
*   **Session Memory**: The Assistant retains context. You can ask follow-ups like *"Show the details for the second one"*.
*   **Read-Only Safety**: The generated SQL is executed in read-only mode. Commands like `UPDATE` or `DELETE` are blocked.

---

## 5. Knowledge Base & Document Ingestion

Managers upload and manage documents used to ground RAG retrievals:
*   **Company Policies**: Upload compliance PDFs. Toggling a policy active/inactive controls whether NLI trigger evaluations check it.
*   **SOP Procedures**: Ingest step-by-step resolution workflows. The system maps these to expected step graphs to calculate process adherence.
*   **FAQ & Knowledge Base**: Manage FAQ question/answer pairs and reference documents for Q&A query synthesis.
