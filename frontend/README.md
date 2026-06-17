# VocalMind Frontend

Manager and agent web UI for VocalMind, built with React 18, Vite, Tailwind v4, MUI, and Radix UI.

## Main Areas

1. Manager dashboard and session inspector
2. Call detail pages with transcript playback and evaluation panels
3. Knowledge-base management
4. Assistant and agent-facing workflows

## Explainability UI

The manager session-detail page now includes the Evidence-Anchored Explainability panel.

It renders:

1. Span-Level Trigger Attribution cards
2. Retrieval Provenance Scoring cards
3. Timestamp jump actions that sync cards back to audio playback

See **[Evidence-Anchored Explainability Layer](../docs/explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md)** for the full feature contract.

## Development

Install dependencies:

```bash
pnpm install
```

Start the dev server:

```bash
pnpm run dev
```

Type-check:

```bash
pnpm run lint
```

Run tests:

```bash
pnpm run test
```

## Testing & Coverage

VocalMind uses **Cypress** for E2E testing and **Vitest** for unit testing. 

### E2E Code Coverage
Instrumentation is handled via `babel-plugin-istanbul` during the production build. To run E2E tests with coverage reporting:

```bash
# From the repository root
make fe-e2e-cov
```

This generates an HTML report in `frontend/coverage/index.html`.

## Relevant Files

1. `src/app/components/manager/SessionInspector.tsx`
2. `src/app/components/manager/SessionDetail.tsx`
3. `src/app/components/manager/EvidenceAnchoredExplainabilityPanel.tsx`
4. `src/app/services/api.ts`

## Targeted UI Tests

1. `src/tests/SessionInspector.test.tsx`
2. `src/tests/SessionDetail.test.tsx`
3. `src/tests/LLMTriggerSections.test.tsx`
