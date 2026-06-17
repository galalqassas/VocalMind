# VocalMind Frontend Architecture & Component Guide

The VocalMind frontend is a React 18 Single Page Application (SPA) built using **Vite** for bundling, **Tailwind CSS v4** for styling utilities, **Material UI (MUI)** for complex UI tables and charts, and **Radix UI** primitives for accessible components (implemented via shadcn/ui wrappers).

This document serves as the guide for the frontend directory layout, routing system, API connection layer, and key interface components.

---

## 1. Directory Structure

```text
frontend/
├── src/
│   ├── main.tsx           # Application root entry point
│   ├── vite-env.d.ts      # Vite TypeScript environment definitions
│   ├── styles/            # Global styling, Tailwind imports, and fonts
│   ├── app/
│   │   ├── App.tsx        # Integrates AuthProvider, ThemeProvider, and Router
│   │   ├── routes.tsx     # Centralized react-router v7 path mappings
│   │   ├── contexts/      # AuthContext and ThemeContext state managers
│   │   ├── data/          # richMockData.ts supplying demo client layers
│   │   ├── services/
│   │   │   └── api.ts     # The 60KB typed API client and fetch wrapper
│   │   ├── components/
│   │   │   ├── layouts/   # ManagerLayout and AgentLayout sidebar structures
│   │   │   ├── ui/        # 48 reusable shadcn wrapper components
│   │   │   ├── manager/   # Manager portal detail pages and dashboard
│   │   │   ├── agent/     # Agent portal coaching pages and dashboard
│   │   │   └── shared/    # Audio players and common visual cards
│   │   └── pages/
│   │       └── Login.tsx  # Central login portal
```

---

## 2. Routing System (`routes.tsx`)

VocalMind utilizes `react-router` v7 to enforce path configurations, guarding agent and manager portals via a custom `ProtectedRoute.tsx` wrapper:

| Path | View Component | Role Required | Description |
| :--- | :--- | :--- | :--- |
| `/` | `LandingPage` | None | Landing description of the platform. |
| `/login` | `Login` | None | Multi-tenant auth entry screen. |
| **`/manager`** | `ManagerLayout` | **manager** | Parent wrapper with manager sidebar menu. |
| ├── `(index)` | `ManagerDashboard` | manager | Rolls up overall KPIs and leaderboard. |
| ├── `/inspector` | `SessionInspector` | manager | Searchable call table with reprocessing/filters. |
| ├── `/inspector/:id` | `SessionDetail` | manager | Comprehensive call transcription & explainability detail. |
| ├── `/assistant` | `ManagerAssistant` | manager | NL-to-SQL conversational query agent. |
| ├── `/knowledge` | `KnowledgeBase` | manager | PDF ingestion, active rules lists, and FAQ editing. |
| ├── `/settings` | `ManagerSettings` | manager | Organization status and general configs. |
| **`/agent`** | `AgentLayout` | **agent** | Parent wrapper with agent sidebar menu. |
| ├── `(index)` | `AgentDashboard` | agent | Personal score trends and summary metrics. |
| ├── `/calls` | `AgentCalls` | agent | List of calls processed for this agent. |
| ├── `/calls/:id` | `AgentCallDetail` | agent | Personal call transcript review and coaching triggers. |
| ├── `/settings` | `SettingsPage` | agent | Personal user profile configurations. |

---

## 3. Global State Managers (`contexts/`)

*   **`AuthContext`**: Manages user authentication state. On login success, stores credentials in a session and sets the Authorization Bearer token. Persists user configurations inside `sessionStorage` to allow reload preservation. Integrates HttpOnly cookie sync mechanisms for API endpoints.
*   **`ThemeContext`**: Stores visual theme configurations (Light vs Dark mode), inserting appropriate `.dark` classes to enable Tailwind's dark utility styling.

---

## 4. The API Client Service (`services/api.ts`)

The API client orchestrates REST calls to the backend (`http://localhost:8000/api/v1`), adding Bearer tokens in headers. 

### 4.1 Mock Mode Toggle
To facilitate rapid offline demonstrations and serverless preview builds (e.g. Vercel), `api.ts` features a dual execution mode controlled by configuration flags:
*   `USE_MOCK_API` / `USE_MOCK_AUTH`: If the backend is unavailable or the variables are enabled, the client routes requests through a client-side in-memory mock store (`richMockData.ts`) preserved via `sessionStorage`.

### 4.2 Key Exported Functions
*   `getDashboardStats()`: Retrieves organizational averages.
*   `getInteractions()`: Fetches the searchable list of call records.
*   `getInteractionDetail(id)`: Fetches a single call transcript, diarization segments, and coaching triggers. Caches results for 15 seconds to minimize request overhead on navigation.
*   `sendAssistantQuery(text)`: Posts natural language queries, retrieving the text response and database rows.
*   `uploadPolicyDocument(file)`: Uploads policy PDFs to initiate ingest.
*   `togglePolicy(id)` / `toggleFaq(id)` / `toggleKB(id)`: Controls RAG context availability.

---

## 5. Evidence-Anchored Explainability UI Components

Surfancing LLM evaluation verdicts requires highly specialized interactive components on the manager details page:

### 5.1 `EvidenceAnchoredExplainabilityPanel.tsx`
Renders the diagnostic Evidence Cards beneath the audio playback controls:
*   **Trigger Attributions**: Renders orange/amber warning cards mapping flagged triggers (e.g. *Customer Escalation*, *Policy Deviation*) to the specific transcript utterance.
*   **Retrieval Provenance**: Renders information cards linking RAG compliance verdicts to their specific chunk. Surfaces the matching similarity confidence percentage. Surfaces Knowledge Base queries using distinct indigo styling to differentiate them from the compliance colors.
*   **Audio Jump Interaction**: Hooks call click events on cards to target the audio playback element, jumping the playhead directly to `jump_to_seconds` and blinking the corresponding transcript turn.

### 5.2 `EmotionComparisonPanel.tsx`
Plots comparative charts mapping the acoustic emotion predictions against text-based predictions. Visualizes mismatch boundaries to identify where agent sarcasm or passive-aggression occurred.

---

## 6. Development & Quality Guidelines

*   **Responsive layouts**: Sidebars collapse to mobile layouts. Flex grids automatically adapt tables to narrower viewports.
*   **Shadcn/Radix Wrapper Usage**: All modals, popovers, tooltips, and drop menus must use Radix-wrapped components in `components/ui/` to ensure accessibility and consistent theme transitions.
*   **Unit Tests**: Located under `src/tests/` (e.g., `SessionDetail.test.tsx`), verifying UI updates based on mock API states using Vitest.
