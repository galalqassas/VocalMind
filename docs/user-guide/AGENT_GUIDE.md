# Agent Guide

What a user with the **agent** role can see and do. Route and component map: [FRONTEND_ARCHITECTURE.md](../frontend/FRONTEND_ARCHITECTURE.md).

## Access

- Agents see only their own calls. The backend filters interactions by `agent_id` for agents (`_interaction_scope_filters` in `backend/app/api/routes/interactions.py`).
- The `/manager/*` pages redirect agents to `/agent`. For agents, the backend returns 403 on the Manager Assistant, the review queue, manager corrections and knowledge versioning. The policy/SOP/KB edit endpoints in `backend/app/api/routes/knowledge.py` do not check the role yet.
- The sidebar has **My Performance** (`/agent`) and **My Calls** (`/agent/calls`). Use the header bell for Notifications (`/agent/notifications`) and the user menu for **Settings** (`/agent/settings`).

## My Performance (`/agent`)

- Stat cards: Overall Score, Total Calls, Resolution Rate and Avg Response (Avg Response is empty for newly processed calls: response time is not computed yet).
- **My Score Breakdown**: averages for Empathy Score, Policy Adherence and Resolution.
- **My Weekly Trend**: chart of your interaction scores.
- **My Recent Calls**: your calls, newest first.

## Call detail (`/agent/calls/:id`)

- Audio player with timeline markers. Click a transcript turn to jump the audio to it.
- Analysis tabs (Emotion, Process, Policy, Quality) when LLM analysis is available. Without it, the page shows **Coaching Points**, a list of saved policy findings.
- **Customer Emotion Journey**: the customer's emotion events through the call.
- Evidence panel: links each finding to transcript spans and the policy or SOP it was checked against.

## Disputing an AI finding

1. On a policy finding or an emotion event, click **Flag as incorrect**.
2. Write a short reason. Your manager sees it.
3. Click **Submit flag**. The item then shows **Flag pending review**.

The flag goes to your manager's Review Queue. You get a notification when it is approved or rejected, and also when a manager corrects one of your call's verdicts directly. The UI has no way to withdraw a flag once you submit it.
