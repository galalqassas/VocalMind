/**
 * API client for connecting frontend to the FastAPI backend.
 * Support standard REST API calls or a complete frontend-only rich mock mode for client demos.
 */

import * as richMock from "../data/richMockData";

const API_ROOT = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_BASE = `${API_ROOT.replace(/\/$/, "")}/api/v1`;

/** Mirrors HttpOnly cookie so assistant/history work if the cookie is not sent cross-origin. */
const VM_ACCESS_TOKEN_KEY = "vm_access_token";

// Config flags: default to true for easy serverless hosting on Vercel
const IS_CYPRESS = typeof window !== "undefined" && !!(window as any).Cypress;
const USE_MOCK_API = !IS_CYPRESS && import.meta.env.VITE_USE_MOCK_API !== "false";
const USE_MOCK_AUTH = !IS_CYPRESS && import.meta.env.VITE_USE_MOCK_AUTH !== "false";

function persistAccessToken(accessToken: string | undefined | null) {
  if (typeof sessionStorage === "undefined") return;
  try {
    if (accessToken) sessionStorage.setItem(VM_ACCESS_TOKEN_KEY, accessToken);
    else sessionStorage.removeItem(VM_ACCESS_TOKEN_KEY);
  } catch {
    /* private mode / quota */
  }
}

function clearPersistedAccessToken() {
  persistAccessToken(null);
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;
  const headers = new Headers(options?.headers || {});
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("Authorization") && typeof sessionStorage !== "undefined") {
    try {
      const t = sessionStorage.getItem(VM_ACCESS_TOKEN_KEY);
      if (t) headers.set("Authorization", `Bearer ${t}`);
    } catch {
      /* ignore */
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });

  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }

  // 204 No Content (e.g. DELETE) — no body to parse.
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

// ── Local In-Memory Mock Store with sessionStorage persistence ───────────────

function getStoredItem<T>(key: string, defaultValue: T): T {
  if (typeof window === "undefined" || !window.sessionStorage) return defaultValue;
  const stored = window.sessionStorage.getItem(key);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      return defaultValue;
    }
  }
  return defaultValue;
}

function setStoredItem<T>(key: string, value: T): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  window.sessionStorage.setItem(key, JSON.stringify(value));
}

// Global active arrays initialized from exported data
let mockInteractionsList: any[] = getStoredItem<any[]>("vm_mock_interactions", richMock.richInteractions);
let mockInteractionDetailsMap: any = getStoredItem<any>("vm_mock_interaction_details", richMock.richInteractionDetails);
let mockPoliciesList: any[] = getStoredItem<any[]>("vm_mock_policies", richMock.richPolicies);
let mockFaqsList: any[] = getStoredItem<any[]>("vm_mock_faqs", richMock.richFaqs);
let mockKbList: any[] = getStoredItem<any[]>("vm_mock_kb", richMock.richKb);
let mockAgentsList: any[] = getStoredItem<any[]>("vm_mock_agents", richMock.richAgents);
let mockAssistantHistoryList: any[] = getStoredItem<any[]>("vm_mock_assistant_history", richMock.richAssistantHistory);

// Dynamic Trigger Backfiller for evidence-anchored explainability
function enrichInteractionWithMockTriggers(detail: any): any {
  if (!detail) return detail;
  if (detail.llmTriggers && detail.llmTriggers.available) {
    return detail;
  }

  const interaction = detail.interaction;
  const utterances = detail.utterances || [];
  const violations = detail.policyViolations || [];
  const events = detail.emotionEvents || [];
  const overallScore = interaction?.overallScore ?? 75;
  const resolved = interaction?.resolved ?? true;

  let detectedTopic = "General Inquiry";
  let expectedSteps = ["Greet customer warmly", "Acknowledge core issue", "Diagnose resolution path", "Summarize and closing script"];
  const transcriptText = utterances.map((u: any) => `${u.speaker}: ${u.text}`).join("\n");

  if (transcriptText.toLowerCase().includes("billing") || transcriptText.toLowerCase().includes("payment") || transcriptText.toLowerCase().includes("invoice")) {
    detectedTopic = "Billing Dispute & Payments";
    expectedSteps = ["Greeting & identity verification", "Review billing statement details", "Identify invoice discrepancy", "Explain billing cycle standard", "Provide resolution credit/refund", "Confirm customer understanding", "Summary & closing script"];
  } else if (transcriptText.toLowerCase().includes("login") || transcriptText.toLowerCase().includes("password") || transcriptText.toLowerCase().includes("account")) {
    detectedTopic = "Account Access & Password Reset";
    expectedSteps = ["Greeting & warmth protocol", "Verify email & full name details", "Check account active status", "Send secure MFA reset link", "Guide user through reset screen", "Confirm login works successfully", "Active closing script"];
  } else if (transcriptText.toLowerCase().includes("refund") || transcriptText.toLowerCase().includes("charge")) {
    detectedTopic = "Refund Authorization";
    expectedSteps = ["Verify purchase ID & receipt date", "Confirm purchase is within 30 days", "Evaluate restocking fee condition", "Propose alternate store credit first", "Apply authorized payment refund", "Explain 5-7 day processing time", "Professional wrap-up summary"];
  }

  const peakNegativeEvent = events.find((e: any) => e.newEmotion === "angry" || e.newEmotion === "frustrated");
  const isDissonance = events.length > 0;

  const emotionShift = {
    isDissonanceDetected: isDissonance,
    dissonanceType: isDissonance ? "Cross-Modal Contradiction" : "None",
    rootCause: isDissonance 
      ? `Customer expressed ${peakNegativeEvent?.newEmotion || "frustrated"} acoustics due to repeated hold periods, while agent text transcribed as standard polite phrasing.` 
      : "Sentiment polarity and acoustic emotion are aligned across the interaction.",
    currentCustomerEmotion: peakNegativeEvent?.newEmotion || "neutral",
    currentEmotionReasoning: isDissonance 
      ? `Peak tension occurred at timestamp ${peakNegativeEvent?.timestamp || "00:45"} when the customer raised their voice.`
      : "Customer remained calm and neutral throughout the call flow.",
    counterfactualCorrection: isDissonance 
      ? "If the agent had validated the customer's frustration immediately rather than explaining technical procedures, the escalation risk would have dropped." 
      : "N/A",
    evidenceQuotes: peakNegativeEvent ? [peakNegativeEvent.justification] : [],
    citations: utterances.slice(1, 3).map((u: any, idx: number) => ({
      source: "transcript",
      speaker: u.speaker,
      quote: u.text,
      utteranceIndex: idx + 1
    })),
    insufficientEvidence: false,
    confidenceScore: 0.89
  };

  const missingSopSteps = resolved ? [] : [expectedSteps[expectedSteps.length - 2]];
  const processAdherence = {
    detectedTopic,
    isResolved: resolved,
    efficiencyScore: Math.round(overallScore / 10),
    justification: resolved 
      ? `Agent followed all crucial standard operating steps to address the customer's ${detectedTopic} inquiry successfully.`
      : `Agent failed to execute crucial resolution step "${expectedSteps[expectedSteps.length - 2]}" resulting in unresolved state.`,
    missingSopSteps,
    evidenceQuotes: utterances.slice(-2).map((u: any) => u.text),
    citations: utterances.slice(-2).map((u: any, idx: number) => ({
      source: "transcript",
      speaker: u.speaker,
      quote: u.text,
      utteranceIndex: utterances.length - 2 + idx
    })),
    insufficientEvidence: false,
    confidenceScore: 0.94
  };

  const hasViolation = violations.length > 0;
  const nliPolicy = {
    nliCategory: hasViolation ? "Contradiction" : "Entailment",
    justification: hasViolation
      ? `Agent statement conflicted directly with the organization's policy: "${violations[0].policyName}".`
      : "Agent statements and disclosures strictly conform to active compliance policy parameters.",
    evidenceQuotes: violations.map((v: any) => v.description),
    citations: [
      {
        source: "policy",
        speaker: "system",
        quote: hasViolation ? violations[0].description : "All agents must maintain active greeting protocol.",
        utteranceIndex: null
      }
    ],
    policyVersion: "1.4.2",
    policyEffectiveAt: "2026-01-15T00:00:00Z",
    policyCategory: "General Compliance",
    conflictResolutionApplied: false,
    insufficientEvidence: false,
    confidenceScore: 0.91,
    policyAlignmentScore: overallScore / 100
  };

  const triggerAttributions: any[] = [];
  
  // SOP Attribution
  triggerAttributions.push({
    attributionId: "trig-sop",
    family: "sop",
    triggerType: "SOP Adherence Check",
    title: resolved ? "Resolution SOP Followed" : "Missing Resolution Process",
    verdict: resolved ? "Supported" : "Partial Attempt",
    confidence: 0.95,
    evidenceSpan: utterances.length > 0 ? {
      speaker: utterances[Math.min(2, utterances.length - 1)].speaker,
      quote: utterances[Math.min(2, utterances.length - 1)].text,
      timestamp: utterances[Math.min(2, utterances.length - 1)].timestamp,
      startSeconds: utterances[Math.min(2, utterances.length - 1)].startTime,
      endSeconds: utterances[Math.min(2, utterances.length - 1)].endTime
    } : null,
    policyReference: {
      source: "sop",
      reference: `${detectedTopic} Resolution Graph`,
      clause: expectedSteps.join(" -> "),
      provenance: "Qdrant SOP Parents Collection"
    },
    reasoning: resolved 
      ? `The agent followed standard procedure steps. Identity was verified, diagnostic questions were asked, and a final resolution was confirmed.`
      : `The agent failed to perform proper supervisor escalation when requested, which is required under standard procedure.`,
    evidenceChain: expectedSteps.slice(0, 3).map((step, idx) => `${idx + 1}. Executed step: ${step}`),
    supportingQuotes: utterances.slice(0, 2).map((u: any) => u.text)
  });

  // Policy Attribution
  triggerAttributions.push({
    attributionId: "trig-policy",
    family: "policy",
    triggerType: "Policy Compliance Verification",
    title: hasViolation ? "Compliance Protocol Breached" : "Policy Alignment Standard",
    verdict: hasViolation ? "Contradiction" : "Supported",
    confidence: 0.92,
    evidenceSpan: violations.length > 0 ? {
      speaker: "agent",
      quote: violations[0].reasoning || "I cannot do that.",
      timestamp: "01:15",
      startSeconds: 75,
      endSeconds: 80
    } : (utterances.length > 0 ? {
      speaker: utterances[0].speaker,
      quote: utterances[0].text,
      timestamp: utterances[0].timestamp,
      startSeconds: utterances[0].startTime,
      endSeconds: utterances[0].endTime
    } : null),
    policyReference: {
      source: "policy",
      reference: hasViolation ? violations[0].policyName : "Customer Interaction Guidelines",
      clause: hasViolation 
        ? violations[0].description 
        : "Agents must greet customers within 5 seconds of the call starting and ensure secure data handling.",
      provenance: "Qdrant Parents Policy Collection"
    },
    reasoning: hasViolation
      ? `Policy breach verified. The agent failed to comply with active guideline: "${violations[0].policyName}".`
      : "Agent followed active data privacy rules, refraining from asking sensitive card numbers and providing professional greeting scripting.",
    evidenceChain: hasViolation 
      ? [`1. Breach detected: ${violations[0].policyName}`, `2. Explanation: ${violations[0].reasoning}`]
      : ["1. Greeted within 3s", "2. Identity verified via secure link", "3. Standard wrap-up script used"],
    supportingQuotes: hasViolation ? [violations[0].description] : [utterances[0]?.text || ""]
  });

  // Emotion Attribution
  triggerAttributions.push({
    attributionId: "trig-emotion",
    family: "emotion",
    triggerType: "Peak Emotion & Dissonance Shift",
    title: isDissonance ? "Cross-Modal Dissonance Triggered" : "Emotion Trajectory Aligned",
    verdict: isDissonance ? "Cross-Modal Mismatch" : "No Trigger",
    confidence: 0.88,
    evidenceSpan: peakNegativeEvent ? {
      speaker: peakNegativeEvent.speaker,
      quote: peakNegativeEvent.justification,
      timestamp: peakNegativeEvent.timestamp,
      startSeconds: peakNegativeEvent.jumpToSeconds,
      endSeconds: peakNegativeEvent.jumpToSeconds + 5
    } : (utterances.length > 0 ? {
      speaker: utterances[0].speaker,
      quote: utterances[0].text,
      timestamp: utterances[0].timestamp,
      startSeconds: utterances[0].startTime,
      endSeconds: utterances[0].endTime
    } : null),
    policyReference: {
      source: "policy",
      reference: "Customer Sentiment Standards",
      clause: "Identify sudden acoustic spikes, passive sarcasm, or multi-turn persistent customer frustration.",
      provenance: "VocalMind Dual-Emotion Fusion Pipeline"
    },
    reasoning: isDissonance 
      ? `Acoustic emotion registered as ${peakNegativeEvent?.newEmotion || "angry"} (intensity: 0.85) while verbal transcript phrasing remained highly formal and polite.`
      : "Customer emotion remained positive or neutral throughout the call timeline.",
    evidenceChain: isDissonance 
      ? ["1. Acoustic shift to negative", "2. Text sentiment remains passive", "3. Conflict flags dissonance warning"]
      : ["1. Initial neutral state", "2. Consistent positive sentiment fusions"],
    supportingQuotes: peakNegativeEvent ? [peakNegativeEvent.justification] : []
  });

  const claimProvenance = [
    {
      claimId: "prov-1",
      claimText: resolved ? `Resolution verified for ${detectedTopic}` : `Escalation requested due to dispute`,
      claimSpan: utterances.length > 0 ? {
        speaker: "agent",
        quote: utterances[utterances.length - 1].text,
        timestamp: utterances[utterances.length - 1].timestamp,
        startSeconds: utterances[utterances.length - 1].startTime,
        endSeconds: utterances[utterances.length - 1].endTime
      } : null,
      retrievedPolicy: {
        source: "policy",
        reference: "Refund & Resolution Guidelines",
        clause: "Agents may authorize resolutions directly when criteria are met."
      },
      semanticSimilarity: 0.94,
      nliVerdict: "Supported",
      confidence: 0.91,
      reasoning: "Agent resolution claim is fully supported by the active organizational FAQ article and compliance policy retrieved chunks.",
      provenance: "Qdrant Collection Parents",
      supportingQuotes: ["Agents may authorize resolutions directly when criteria are met."]
    }
  ];

  detail.llmTriggers = {
    available: true,
    interactionId: interaction.id,
    emotionShift,
    processAdherence,
    nliPolicy,
    explainability: {
      triggerAttributions,
      claimProvenance
    },
    derived: {
      customerText: utterances.filter((u: any) => u.speaker === "customer").map((u: any) => u.text).join(" "),
      acousticEmotion: peakNegativeEvent?.newEmotion || "neutral",
      fusedEmotion: peakNegativeEvent?.newEmotion || "neutral",
      agentStatement: utterances.filter((u: any) => u.speaker === "agent").map((u: any) => u.text).join(" ")
    }
  };

  detail.emotionTriggers = {
    available: true,
    interactionId: interaction.id,
    emotionShift,
    explainability: {
      triggerAttributions: triggerAttributions.filter((a) => a.family === "emotion"),
      claimProvenance: []
    },
    derived: detail.llmTriggers.derived
  };

  detail.ragCompliance = {
    available: true,
    interactionId: interaction.id,
    processAdherence,
    nliPolicy,
    explainability: {
      triggerAttributions: triggerAttributions.filter((a) => a.family !== "emotion"),
      claimProvenance
    },
    policyViolations: violations
  };

  return detail;
}

function mockDashboardStats(): DashboardStats {
  const totalCalls = mockInteractionsList.length;
  const completedCalls = mockInteractionsList.filter(i => i.status === "completed");
  const avgScore = completedCalls.length > 0
    ? Math.round(completedCalls.reduce((acc, curr) => acc + (curr.overallScore || 0), 0) / completedCalls.length * 10) / 10
    : 0;
  const resolutionRate = completedCalls.length > 0
    ? Math.round(completedCalls.filter(i => i.resolved).length / completedCalls.length * 100 * 10) / 10
    : 0;
  const violationCount = completedCalls.filter(i => i.hasViolation).length;

  return {
    kpis: {
      avgScore,
      totalCalls,
      resolutionRate,
      violationCount
    },
    weeklyTrend: richMock.richDashboardStats.weeklyTrend,
    emotionDistribution: richMock.richDashboardStats.emotionDistribution,
    policyCompliance: richMock.richDashboardStats.policyCompliance,
    agentPerformance: richMock.richDashboardStats.agentPerformance as any,
    interactions: mockInteractionsList
  };
}

// ── Dashboard ────────────────────────────────────────────────────────────────

export interface DashboardStats {
  kpis: {
    avgScore: number;
    totalCalls: number;
    resolutionRate: number;
    violationCount: number;
  };
  weeklyTrend: Array<{ day: string; score: number }>;
  emotionDistribution: Array<{ name: string; value: number; color: string }>;
  policyCompliance: Array<{ category: string; rate: number; color: string }>;
  agentPerformance: Array<{
    name: string;
    empathy: number;
    policy: number;
    resolution: number;
    overallScore: number;
    trend: "up" | "down";
  }>;
  interactions: InteractionSummary[];
}

export function getDashboardStats(): Promise<DashboardStats> {
  if (USE_MOCK_API) {
    return Promise.resolve(mockDashboardStats());
  }
  return apiFetch<DashboardStats>("/dashboard/stats");
}

// ── Interactions ──────────────────────────────────────────────────────────────

export interface ProcessingFailureBrief {
  stage: string;
  errorMessage?: string | null;
}

export interface InteractionSummary {
  id: string;
  agentName: string;
  agentId: string;
  date: string;
  time: string;
  duration: string;
  language: string;
  overallScore: number;
  empathyScore: number;
  policyScore: number;
  resolutionScore: number;
  resolved: boolean;
  hasViolation: boolean;
  hasOverlap: boolean;
  responseTime: string;
  status: string;
  audioFilePath?: string | null;
  processingFailures?: ProcessingFailureBrief[];
}

export function getInteractions(): Promise<InteractionSummary[]> {
  if (USE_MOCK_API) {
    return Promise.resolve(mockInteractionsList);
  }
  return apiFetch<InteractionSummary[]>("/interactions");
}

export interface CreateInteractionResult {
  interactionId: string;
  status: string;
  audioFilePath: string;
  agentId: string;
  uploadedBy: string;
  processingJobs: Array<{
    stage: string;
    status: string;
    retryCount: number;
    errorMessage?: string | null;
  }>;
}

export function createInteraction(file: File, agentId?: string): Promise<CreateInteractionResult> {
  if (USE_MOCK_API) {
    const id = "d0000000-0000-0000-0000-00000000" + Math.floor(100000 + Math.random() * 900000);
    const agent = mockAgentsList.find(a => a.id === agentId) || mockAgentsList[0] || { name: "Sara Agent", id: "b0000000-0000-0000-0000-000000000003" };
    
    const newInteraction = {
      id,
      agentName: agent.name,
      agentId: agent.id,
      date: new Date().toISOString().split("T")[0],
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      duration: "3:45",
      language: "en",
      overallScore: 82.0,
      empathyScore: 88.0,
      policyScore: 75.0,
      resolutionScore: 83.0,
      resolved: true,
      hasViolation: false,
      hasOverlap: false,
      responseTime: "2.1s",
      status: "completed",
      audioFilePath: null,
      processingFailures: []
    };
    
    mockInteractionsList.unshift(newInteraction);
    setStoredItem("vm_mock_interactions", mockInteractionsList);
    
    const newDetail = {
      interaction: newInteraction,
      utterances: [
        {
          id: "utt-new-1",
          interactionId: id,
          speaker: "agent",
          sequenceIndex: 0,
          text: `Thank you for calling support. My name is ${agent.name}. How can I help you?`,
          startTime: 0,
          endTime: 5,
          timestamp: "00:00",
          emotion: "neutral",
          confidence: 0.95
        },
        {
          id: "utt-new-2",
          interactionId: id,
          speaker: "customer",
          sequenceIndex: 1,
          text: `Hi, I am calling about a charge on my invoice for ${file.name || "services"}. I don't understand what this fee is.`,
          startTime: 6,
          endTime: 12,
          timestamp: "00:06",
          emotion: "frustrated",
          confidence: 0.88
        },
        {
          id: "utt-new-3",
          interactionId: id,
          speaker: "agent",
          sequenceIndex: 2,
          text: "I completely understand. Let me check your account billing history right away to clarify that for you.",
          startTime: 13,
          endTime: 19,
          timestamp: "00:13",
          emotion: "empathetic",
          confidence: 0.94
        },
        {
          id: "utt-new-4",
          interactionId: id,
          speaker: "customer",
          sequenceIndex: 3,
          text: "Great! That would be very helpful.",
          startTime: 20,
          endTime: 23,
          timestamp: "00:20",
          emotion: "neutral",
          confidence: 0.90
        }
      ],
      emotionComparison: {
        totalUtterances: 4,
        distributions: {
          acoustic: [{ emotion: "neutral", count: 3, pct: 75 }, { emotion: "frustrated", count: 1, pct: 25 }],
          text: [{ emotion: "neutral", count: 3, pct: 75 }, { emotion: "frustrated", count: 1, pct: 25 }],
          fused: [{ emotion: "neutral", count: 3, pct: 75 }, { emotion: "frustrated", count: 1, pct: 25 }]
        },
        quality: {
          acousticTextAgreementRate: 100.0,
          fusedMatchesAcousticRate: 100.0,
          fusedMatchesTextRate: 100.0,
          disagreementCount: 0
        }
      },
      emotionEvents: [
        {
          id: "evt-new-1",
          interactionId: id,
          previousEmotion: "neutral",
          newEmotion: "frustrated",
          fromEmotion: "neutral",
          toEmotion: "frustrated",
          jumpToSeconds: 6,
          timestamp: "00:06",
          confidenceScore: 0.88,
          delta: -0.4,
          speaker: "customer",
          justification: "Customer questioned unexpected fees on invoice."
        }
      ],
      policyViolations: []
    };
    
    mockInteractionDetailsMap[id] = newDetail;
    setStoredItem("vm_mock_interaction_details", mockInteractionDetailsMap);
    
    return Promise.resolve({
      interactionId: id,
      status: "completed",
      audioFilePath: `/audio/${file.name}`,
      agentId: agent.id,
      uploadedBy: "b0000000-0000-0000-0000-000000000001",
      processingJobs: []
    });
  }

  const formData = new FormData();
  formData.append("file", file);
  if (agentId) {
    formData.append("agent_id", agentId);
  }
  return apiFetch<CreateInteractionResult>("/interactions", {
    method: "POST",
    body: formData,
  });
}

export interface ProcessingStatusResult {
  interactionId: string;
  status: string;
  jobs: Array<{
    stage: string;
    status: string;
    retryCount: number;
    errorMessage?: string | null;
    startedAt?: string | null;
    completedAt?: string | null;
  }>;
}

export function getInteractionProcessingStatus(id: string): Promise<ProcessingStatusResult> {
  if (USE_MOCK_API) {
    return Promise.resolve({
      interactionId: id,
      status: "completed",
      jobs: []
    });
  }
  return apiFetch<ProcessingStatusResult>(`/interactions/${id}/processing-status`);
}

export interface UtteranceData {
  id: string;
  interactionId: string;
  speaker: string;
  sequenceIndex?: number;
  text: string;
  startTime: number;
  endTime: number;
  timestamp: string;
  emotion: string;
  confidence: number;
  textEmotion?: string;
  textConfidence?: number;
  fusedEmotion?: string;
  fusedConfidence?: number;
  fusionModel?: string;
}

export interface EmotionEventData {
  id: string;
  interactionId: string;
  previousEmotion: string;
  newEmotion: string;
  fromEmotion: string;
  toEmotion: string;
  jumpToSeconds: number;
  timestamp: string;
  confidenceScore: number;
  delta: number;
  speaker: string;
  llmJustification: string;
  justification: string;
}

export interface PolicyViolationData {
  id: string;
  interactionId: string;
  policyName: string;
  policyTitle: string;
  category: string;
  description: string;
  reasoning: string;
  severity: string;
  score: number;
  timestamp?: string;
}

export interface InteractionDetailInfo extends InteractionSummary {
  audioFilePath?: string | null;
}

export interface EmotionDistribution {
  emotion: string;
  count: number;
  pct: number;
}

export interface EmotionComparison {
  interactionId?: string;
  totalUtterances: number;
  distributions: {
    acoustic: EmotionDistribution[];
    text: EmotionDistribution[];
    fused: EmotionDistribution[];
  };
  quality: {
    acousticTextAgreementRate: number;
    fusedMatchesAcousticRate: number;
    fusedMatchesTextRate: number;
    disagreementCount: number;
  };
  evidence?: {
    emotionShiftQuotes?: string[];
    processAdherenceQuotes?: string[];
    nliPolicyQuotes?: string[];
    citations?: Array<{
      source: "acoustic" | "text" | "fused";
      speaker?: string;
      quote: string;
      utteranceIndex?: number;
    }>;
  };
}

export interface LLMEvidenceCitation {
  source: "transcript" | "policy" | "sop" | "acoustic" | "kb";
  speaker?: "customer" | "agent" | "system" | "unknown";
  quote: string;
  utteranceIndex?: number | null;
}

export interface ExplainabilitySpan {
  utteranceIndex?: number | null;
  speaker?: "customer" | "agent" | "system" | "unknown";
  quote: string;
  timestamp?: string | null;
  startSeconds?: number | null;
  endSeconds?: number | null;
}

export interface ExplainabilityPolicyReference {
  source: "policy" | "sop" | "kb";
  reference: string;
  clause: string;
  docType?: string | null;
  docId?: string | null;
  ruleId?: string | null;
  stepNumber?: string | null;
  severity?: string | null;
  policyRef?: string[];
  version?: string | null;
  category?: string | null;
  provenance?: string | null;
}

export interface TriggerAttribution {
  attributionId: string;
  family: "emotion" | "sop" | "policy";
  triggerType: string;
  title: string;
  verdict:
    | "Supported"
    | "Partial Attempt"
    | "Neutral"
    | "Contradiction"
    | "Cross-Modal Mismatch"
    | "No Trigger"
    | "Insufficient Evidence";
  confidence?: number | null;
  evidenceSpan?: ExplainabilitySpan | null;
  policyReference?: ExplainabilityPolicyReference | null;
  reasoning: string;
  evidenceChain: string[];
  supportingQuotes: string[];
}

export interface ClaimProvenance {
  claimId: string;
  claimText: string;
  claimSpan?: ExplainabilitySpan | null;
  retrievedPolicy?: ExplainabilityPolicyReference | null;
  semanticSimilarity?: number | null;
  nliVerdict:
    | "Supported"
    | "Partial Attempt"
    | "Neutral"
    | "Contradiction"
    | "Cross-Modal Mismatch"
    | "No Trigger"
    | "Insufficient Evidence";
  confidence?: number | null;
  reasoning: string;
  provenance: string;
  supportingQuotes: string[];
}

export interface EvidenceAnchoredExplainability {
  triggerAttributions: TriggerAttribution[];
  claimProvenance: ClaimProvenance[];
}

export interface LLMEmotionShift {
  isDissonanceDetected: boolean;
  dissonanceType: string;
  rootCause: string;
  currentCustomerEmotion?: string;
  currentEmotionReasoning?: string;
  counterfactualCorrection: string;
  evidenceQuotes: string[];
  citations: LLMEvidenceCitation[];
  insufficientEvidence?: boolean;
  confidenceScore?: number | null;
}

export interface LLMProcessAdherence {
  detectedTopic: string;
  isResolved: boolean;
  efficiencyScore: number;
  justification: string;
  missingSopSteps: string[];
  evidenceQuotes: string[];
  citations: LLMEvidenceCitation[];
  insufficientEvidence?: boolean;
  confidenceScore?: number | null;
}

export interface LLMNliPolicy {
  nliCategory: "Entailment" | "Benign Deviation" | "Contradiction" | "Policy Hallucination";
  justification: string;
  evidenceQuotes: string[];
  citations: LLMEvidenceCitation[];
  policyVersion?: string | null;
  policyEffectiveAt?: string | null;
  policyCategory?: string | null;
  conflictResolutionApplied?: boolean;
  insufficientEvidence?: boolean;
  confidenceScore?: number | null;
  policyAlignmentScore?: number | null;
}

export interface LLMTriggerReport {
  available: boolean;
  error?: string;
  orgFilter?: string | null;
  forcedRerun?: boolean;
  interactionId?: string;
  emotionShift?: LLMEmotionShift;
  processAdherence?: LLMProcessAdherence;
  nliPolicy?: LLMNliPolicy;
  explainability?: EvidenceAnchoredExplainability;
  derived?: {
    customerText: string;
    acousticEmotion: string;
    fusedEmotion: string;
    agentStatement: string;
  };
}

export interface EmotionTriggerReport {
  available: boolean;
  error?: string;
  orgFilter?: string | null;
  forcedRerun?: boolean;
  interactionId?: string;
  emotionShift?: LLMEmotionShift;
  explainability?: EvidenceAnchoredExplainability;
  derived?: {
    customerText: string;
    acousticEmotion: string;
    fusedEmotion: string;
    agentStatement: string;
  };
}

export interface RagComplianceReport {
  available: boolean;
  error?: string;
  orgFilter?: string | null;
  forcedRerun?: boolean;
  interactionId?: string;
  processAdherence?: LLMProcessAdherence;
  nliPolicy?: LLMNliPolicy;
  explainability?: EvidenceAnchoredExplainability;
  policyViolations?: PolicyViolationData[];
}

export interface InteractionDetail {
  interaction: InteractionDetailInfo;
  utterances: UtteranceData[];
  emotionEvents: EmotionEventData[];
  policyViolations: PolicyViolationData[];
  emotionComparison?: EmotionComparison;
  ragCompliance?: RagComplianceReport | null;
  emotionTriggers?: EmotionTriggerReport | null;
  llmTriggers?: LLMTriggerReport | null;
  processingFailures?: ProcessingFailureBrief[];
}

type InteractionDetailOptions = {
  includeLLMTriggers?: boolean;
  llmOrgFilter?: string;
  llmForceRerun?: boolean;
  skipCache?: boolean;
};

type CachedInteractionDetail = {
  expiresAt: number;
  data: InteractionDetail;
};

const interactionDetailCache = new Map<string, CachedInteractionDetail>();
const INTERACTION_DETAIL_CACHE_TTL_MS = 15_000;

export function getInteractionDetail(
  id: string,
  options?: InteractionDetailOptions,
): Promise<InteractionDetail> {
  if (USE_MOCK_API) {
    const baseDetail = mockInteractionDetailsMap[id];
    if (!baseDetail) {
      return Promise.reject(new Error(`Interaction detail not found for ID ${id}`));
    }
    // Deep clone to prevent mutations
    const detail = JSON.parse(JSON.stringify(baseDetail));
    const enriched = enrichInteractionWithMockTriggers(detail);
    return Promise.resolve(enriched);
  }

  const params = new URLSearchParams();
  if (options?.includeLLMTriggers) {
    params.set("include_llm_triggers", "true");
  }
  if (options?.llmOrgFilter) {
    params.set("llm_org_filter", options.llmOrgFilter);
  }
  if (options?.llmForceRerun) {
    params.set("llm_force_rerun", "true");
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const cacheKey = `${id}|${suffix}`;

  if (!options?.skipCache) {
    const cached = interactionDetailCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return Promise.resolve(cached.data);
    }
  }

  return apiFetch<InteractionDetail>(`/interactions/${id}${suffix}`).then((data) => {
    if (!options?.skipCache) {
      interactionDetailCache.set(cacheKey, {
        data,
        expiresAt: Date.now() + INTERACTION_DETAIL_CACHE_TTL_MS,
      });
    }
    return data;
  });
}

export function getAudioUrl(interactionId: string): string {
  if (USE_MOCK_API) {
    return ""; // Empty string triggers standard dummy wav generator in browser
  }
  return `${API_BASE}/interactions/${interactionId}/audio`;
}

export interface ReprocessResult {
  interactionId: string;
  status: string;
  queued: boolean;
  processingJobs: Array<{
    stage: string;
    status: string;
    retryCount: number;
    errorMessage?: string | null;
  }>;
}

export function reprocessInteraction(id: string, options?: { force?: boolean }): Promise<ReprocessResult> {
  if (USE_MOCK_API) {
    const interaction = mockInteractionsList.find(i => i.id === id);
    if (interaction) {
      interaction.status = "completed";
    }
    setStoredItem("vm_mock_interactions", mockInteractionsList);
    return Promise.resolve({
      interactionId: id,
      status: "completed",
      queued: false,
      processingJobs: []
    });
  }

  const suffix = options?.force ? "?force=true" : "";
  return apiFetch<ReprocessResult>(`/interactions/${id}/reprocess${suffix}`, {
    method: "POST",
  });
}

export function deleteInteraction(id: string): Promise<void> {
  if (USE_MOCK_API) {
    mockInteractionsList = mockInteractionsList.filter(i => i.id !== id);
    setStoredItem("vm_mock_interactions", mockInteractionsList);
    if (mockInteractionDetailsMap[id]) {
      delete mockInteractionDetailsMap[id];
      setStoredItem("vm_mock_interaction_details", mockInteractionDetailsMap);
    }
    return Promise.resolve();
  }

  return apiFetch<void>(`/interactions/${id}`, {
    method: "DELETE",
  });
}

// ── Knowledge Base ───────────────────────────────────────────────────────────

export interface PolicyData {
  id: string;
  documentType: "policy";
  title: string;
  category: string;
  content: string;
  preview: string;
  lastUpdated: string;
  isActive: boolean;
  usageCount: number;
}

export function getPolicies(): Promise<PolicyData[]> {
  if (USE_MOCK_API) return Promise.resolve(mockPoliciesList as PolicyData[]);
  return apiFetch<PolicyData[]>("/knowledge/policies");
}

export function uploadPolicyDocument(data: { title?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const id = "pol-new-" + Math.floor(1000 + Math.random() * 9000);
    const newPolicy = {
      id,
      documentType: "policy" as const,
      title: data.title || data.file.name,
      category: data.category || "General",
      content: `Uploaded policy document content for ${data.file.name}. Secure verification rules apply.`,
      preview: `Uploaded policy document content for ${data.file.name}...`,
      lastUpdated: new Date().toISOString().split("T")[0],
      isActive: true,
      usageCount: 0
    };
    mockPoliciesList.unshift(newPolicy);
    setStoredItem("vm_mock_policies", mockPoliciesList);
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.title) formData.append("title", data.title);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>("/knowledge/policies/upload", {
    method: "POST",
    body: formData,
  });
}

export function replacePolicyDocument(id: string, data: { title?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const policy = mockPoliciesList.find(p => p.id === id);
    if (policy) {
      policy.title = data.title || data.file.name;
      policy.lastUpdated = new Date().toISOString().split("T")[0];
      setStoredItem("vm_mock_policies", mockPoliciesList);
    }
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.title) formData.append("title", data.title);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>(`/knowledge/policies/${id}/upload`, {
    method: "PATCH",
    body: formData,
  });
}

export function createPolicy(data: { title: string; category: string; content: string }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const id = "pol-new-" + Math.floor(1000 + Math.random() * 9000);
    const newPolicy = {
      id,
      documentType: "policy" as const,
      title: data.title,
      category: data.category,
      content: data.content,
      preview: data.content.substring(0, 100) + "...",
      lastUpdated: new Date().toISOString().split("T")[0],
      isActive: true,
      usageCount: 0
    };
    mockPoliciesList.unshift(newPolicy);
    setStoredItem("vm_mock_policies", mockPoliciesList);
    return Promise.resolve({ id });
  }

  return apiFetch<{ id: string }>("/knowledge/policies", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updatePolicy(id: string, data: { title?: string; category?: string; content?: string }): Promise<void> {
  if (USE_MOCK_API) {
    const policy = mockPoliciesList.find(p => p.id === id);
    if (policy) {
      if (data.title) policy.title = data.title;
      if (data.category) policy.category = data.category;
      if (data.content) {
        policy.content = data.content;
        policy.preview = data.content.substring(0, 100) + "...";
      }
      policy.lastUpdated = new Date().toISOString().split("T")[0];
      setStoredItem("vm_mock_policies", mockPoliciesList);
    }
    return Promise.resolve();
  }

  return apiFetch<void>(`/knowledge/policies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function togglePolicy(id: string): Promise<{ isActive: boolean }> {
  if (USE_MOCK_API) {
    const policy = mockPoliciesList.find(p => p.id === id);
    const state = policy ? !policy.isActive : false;
    if (policy) {
      policy.isActive = state;
      setStoredItem("vm_mock_policies", mockPoliciesList);
    }
    return Promise.resolve({ isActive: state });
  }

  return apiFetch<{ isActive: boolean }>(`/knowledge/policies/${id}/toggle`, {
    method: "POST",
  });
}

export function deletePolicy(id: string): Promise<void> {
  if (USE_MOCK_API) {
    mockPoliciesList = mockPoliciesList.filter(p => p.id !== id);
    setStoredItem("vm_mock_policies", mockPoliciesList);
    return Promise.resolve();
  }

  return apiFetch<void>(`/knowledge/policies/${id}`, {
    method: "DELETE",
  });
}

export interface FAQData {
  id: string;
  documentType: "faq";
  question: string;
  answer: string;
  preview: string;
  category: string;
  isActive: boolean;
  usageCount: number;
}

export function getFaqs(): Promise<FAQData[]> {
  if (USE_MOCK_API) return Promise.resolve(mockFaqsList as FAQData[]);
  return apiFetch<FAQData[]>("/knowledge/faqs");
}

export function uploadFaqDocument(data: { question?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const id = "faq-new-" + Math.floor(1000 + Math.random() * 9000);
    const newFaq = {
      id,
      documentType: "faq" as const,
      question: data.question || data.file.name,
      answer: `FAQ parsed answers successfully resolved for document ${data.file.name}.`,
      preview: `FAQ parsed answers successfully resolved for...`,
      category: data.category || "General",
      isActive: true,
      usageCount: 0
    };
    mockFaqsList.unshift(newFaq);
    setStoredItem("vm_mock_faqs", mockFaqsList);
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.question) formData.append("question", data.question);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>("/knowledge/faqs/upload", {
    method: "POST",
    body: formData,
  });
}

export function replaceFaqDocument(id: string, data: { question?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const faq = mockFaqsList.find(f => f.id === id);
    if (faq) {
      faq.question = data.question || data.file.name;
      setStoredItem("vm_mock_faqs", mockFaqsList);
    }
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.question) formData.append("question", data.question);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>(`/knowledge/faqs/${id}/upload`, {
    method: "PATCH",
    body: formData,
  });
}

export function createFaq(data: { question: string; answer: string; category: string }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const id = "faq-new-" + Math.floor(1000 + Math.random() * 9000);
    const newFaq = {
      id,
      documentType: "faq" as const,
      question: data.question,
      answer: data.answer,
      preview: data.answer.substring(0, 100) + "...",
      category: data.category,
      isActive: true,
      usageCount: 0
    };
    mockFaqsList.unshift(newFaq);
    setStoredItem("vm_mock_faqs", mockFaqsList);
    return Promise.resolve({ id });
  }

  return apiFetch<{ id: string }>("/knowledge/faqs", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateFaq(id: string, data: { question?: string; answer?: string; category?: string }): Promise<void> {
  if (USE_MOCK_API) {
    const faq = mockFaqsList.find(f => f.id === id);
    if (faq) {
      if (data.question) faq.question = data.question;
      if (data.answer) {
        faq.answer = data.answer;
        faq.preview = data.answer.substring(0, 100) + "...";
      }
      if (data.category) faq.category = data.category;
      setStoredItem("vm_mock_faqs", mockFaqsList);
    }
    return Promise.resolve();
  }

  return apiFetch<void>(`/knowledge/faqs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function toggleFaq(id: string): Promise<{ isActive: boolean }> {
  if (USE_MOCK_API) {
    const faq = mockFaqsList.find(f => f.id === id);
    const state = faq ? !faq.isActive : false;
    if (faq) {
      faq.isActive = state;
      setStoredItem("vm_mock_faqs", mockFaqsList);
    }
    return Promise.resolve({ isActive: state });
  }

  return apiFetch<{ isActive: boolean }>(`/knowledge/faqs/${id}/toggle`, {
    method: "POST",
  });
}

export function deleteFaq(id: string): Promise<void> {
  if (USE_MOCK_API) {
    mockFaqsList = mockFaqsList.filter(f => f.id !== id);
    setStoredItem("vm_mock_faqs", mockFaqsList);
    return Promise.resolve();
  }

  return apiFetch<void>(`/knowledge/faqs/${id}`, {
    method: "DELETE",
  });
}

// ── Knowledge Base ───────────────────────────────────────────────────────────

export interface KBData {
  id: string;
  documentType: "kb";
  title: string;
  category: string;
  content: string;
  preview: string;
  lastUpdated: string;
  isActive: boolean;
  usageCount: number;
}

export function getKBArticles(): Promise<KBData[]> {
  if (USE_MOCK_API) return Promise.resolve(mockKbList as KBData[]);
  return apiFetch<KBData[]>("/knowledge/kb");
}

export function uploadKBDocument(data: { title?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const id = "kb-new-" + Math.floor(1000 + Math.random() * 9000);
    const newKB = {
      id,
      documentType: "kb" as const,
      title: data.title || data.file.name,
      category: data.category || "General",
      content: `Knowledge Base content resolved from parsed file: ${data.file.name}.`,
      preview: `Knowledge Base content resolved from parsed...`,
      lastUpdated: new Date().toISOString().split("T")[0],
      isActive: true,
      usageCount: 0
    };
    mockKbList.unshift(newKB);
    setStoredItem("vm_mock_kb", mockKbList);
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.title) formData.append("title", data.title);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>("/knowledge/kb/upload", {
    method: "POST",
    body: formData,
  });
}

export function replaceKBDocument(id: string, data: { title?: string; category?: string; file: File }): Promise<{ id: string }> {
  if (USE_MOCK_API) {
    const kb = mockKbList.find(k => k.id === id);
    if (kb) {
      kb.title = data.title || data.file.name;
      setStoredItem("vm_mock_kb", mockKbList);
    }
    return Promise.resolve({ id });
  }

  const formData = new FormData();
  if (data.title) formData.append("title", data.title);
  if (data.category) formData.append("category", data.category);
  formData.append("file", data.file);

  return apiFetch<{ id: string }>(`/knowledge/kb/${id}/upload`, {
    method: "PATCH",
    body: formData,
  });
}

export function toggleKB(id: string): Promise<{ isActive: boolean }> {
  if (USE_MOCK_API) {
    const kb = mockKbList.find(k => k.id === id);
    const state = kb ? !kb.isActive : false;
    if (kb) {
      kb.isActive = state;
      setStoredItem("vm_mock_kb", mockKbList);
    }
    return Promise.resolve({ isActive: state });
  }

  return apiFetch<{ isActive: boolean }>(`/knowledge/kb/${id}/toggle`, {
    method: "POST",
  });
}

export function deleteKB(id: string): Promise<void> {
  if (USE_MOCK_API) {
    mockKbList = mockKbList.filter(k => k.id !== id);
    setStoredItem("vm_mock_kb", mockKbList);
    return Promise.resolve();
  }

  return apiFetch<void>(`/knowledge/kb/${id}`, {
    method: "DELETE",
  });
}

// ── Agents ───────────────────────────────────────────────────────────────────

export interface AgentSummary {
  id: string;
  name: string;
  role: string;
}

export function getAgents(): Promise<AgentSummary[]> {
  if (USE_MOCK_API) return Promise.resolve(mockAgentsList);
  return apiFetch<AgentSummary[]>("/agents");
}

export interface AgentPerformance {
  id: string;
  name: string;
  role: string;
}

export function getAgentPerformanceList(): Promise<AgentPerformance[]> {
  if (USE_MOCK_API) return Promise.resolve(mockAgentsList);
  return apiFetch<AgentPerformance[]>("/agents");
}

export interface AgentProfile {
  id: string;
  name: string;
  role: string;
  totalCalls: number;
  callsThisWeek: number;
  teamRank: number;
  avgScore: number;
  overallScore: number;
  empathyScore: number;
  policyScore: number;
  resolutionScore: number;
  resolutionRate: number;
  avgResponseTime: string;
  trend: "up" | "down";
  weeklyTrend: Array<{ day: string; score: number }>;
  recentCalls: Array<{
    id: string;
    date: string;
    time: string;
    score: number;
    duration: string;
    language: string;
    resolved: boolean;
    hasReview: boolean;
  }>;
}

export function getAgentProfile(agentId: string): Promise<AgentProfile> {
  if (USE_MOCK_API) {
    const agent = mockAgentsList.find(a => a.id === agentId) || mockAgentsList[0] || { name: "Sara Agent", id: "b0000000-0000-0000-0000-000000000003" };
    return Promise.resolve({
      id: agent.id,
      name: agent.name,
      role: "Agent Support Professional",
      totalCalls: 34,
      callsThisWeek: 8,
      teamRank: 2,
      avgScore: 78,
      overallScore: 78,
      empathyScore: 82,
      policyScore: 76,
      resolutionScore: 78,
      resolutionRate: 88,
      avgResponseTime: "2.3s",
      trend: "up" as const,
      weeklyTrend: [
        { day: "Mon", score: 72 },
        { day: "Tue", score: 75 },
        { day: "Wed", score: 82 },
        { day: "Thu", score: 78 },
        { day: "Fri", score: 85 }
      ],
      recentCalls: mockInteractionsList
        .filter(i => i.agentName === agent.name)
        .map(i => ({
          id: i.id,
          date: i.date,
          time: i.time,
          score: i.overallScore,
          duration: i.duration,
          language: i.language,
          resolved: i.resolved,
          hasReview: i.hasViolation
        }))
    });
  }

  return apiFetch<AgentProfile>(`/agents/${agentId}`);
}

// ── Assistant ────────────────────────────────────────────────────────────────

export interface AssistantResponse {
  id?: string;
  type: "user" | "ai";
  content: string;
  mode: string;
  sql?: string;
  /** Backend may send camelCase; UI prefers snake_case */
  execution_time?: string;
  executionTime?: string;
  data?: any[];
  success?: boolean;
  /** ISO timestamp from server when message was persisted */
  created_at?: string;
}

function normalizeAssistantPayload(raw: AssistantResponse): AssistantResponse {
  const exec = raw.execution_time ?? raw.executionTime;
  const success = typeof raw.success === "boolean" ? raw.success : true;
  return { ...raw, execution_time: exec, executionTime: exec, success };
}

export function sendAssistantQuery(text: string, mode: "chat" | "voice" = "chat"): Promise<AssistantResponse> {
  if (USE_MOCK_API) {
    let content = "Hello! I am your VocalMind Manager Assistant. I can write read-only queries and help analyze team performance metrics. Ask me about average empathy scores, active policy violations, or individual agent performances.";
    let sql = "SELECT * FROM interactions LIMIT 5;";
    let data: any[] = [];
    
    const query = text.toLowerCase();
    if (query.includes("violation") || query.includes("compliant") || query.includes("breach")) {
      content = "Based on our compliance records, there are a total of **8 calls with active policy violations**. The most common breach is under the **Hold Time Limit** category (4 violations), followed by **Escalation Protocol** (2 violations). Here is a query showing recent non-compliant calls.";
      sql = "SELECT id, agent_name, overall_score, has_violation FROM interactions WHERE has_violation = true ORDER BY date DESC LIMIT 3;";
      data = [
        { id: "d0000000-0000-0000-0000-000000000007", agent_name: "Omar Agent", overall_score: 58, has_violation: true },
        { id: "d0000000-0000-0000-0000-000000000015", agent_name: "Omar Agent", overall_score: 66, has_violation: true },
        { id: "d0000000-0000-0000-0000-000000000011", agent_name: "Omar Agent", overall_score: 67, has_violation: true }
      ];
    } else if (query.includes("sara") || query.includes("sara agent")) {
      content = "**Sara Agent** is our top-performing senior agent this week. She has handled **6 calls** with an outstanding **average overall score of 83.0%**, maintaining **84.0% policy compliance** and achieving **97.0% resolution speed**. She has zero critical policy violations.";
      sql = "SELECT name, role, avg_score, resolution_rate FROM agents WHERE name LIKE '%Sara%' LIMIT 1;";
      data = [{ name: "Sara Agent", role: "Senior Agent", avg_score: 83.0, resolution_rate: 97.0 }];
    } else if (query.includes("mohsen") || query.includes("mohsen agent")) {
      content = "**Mohsen Agent** has managed **5 calls** this week, with an **average score of 76.0%**. His empathy score is currently **72.0%** and policy compliance is **77.0%**. One interaction was flagged with a Hold Time Limit breach but has since been resolved.";
      sql = "SELECT name, role, empathy_score, policy_score FROM agents WHERE name LIKE '%Mohsen%' LIMIT 1;";
      data = [{ name: "Mohsen Agent", role: "Junior Agent", empathy_score: 72.0, policy_score: 77.0 }];
    } else if (query.includes("avg") || query.includes("average") || query.includes("performance") || query.includes("score")) {
      content = "Our team's average customer interaction score is **72.4%**. Sara Agent leads at **83.0%**, followed by Mohsen Agent at **76.0%**, and Omar Agent at **62.0%**. Gaps have been noted in Greet Time and Hold Time limit parameters.";
      sql = "SELECT name, overall_score FROM agents ORDER BY overall_score DESC;";
      data = [
        { name: "Sara Agent", overall_score: 83.0 },
        { name: "Mohsen Agent", overall_score: 76.0 },
        { name: "Omar Agent", overall_score: 62.0 }
      ];
    }
    
    const newMsg: AssistantResponse = {
      id: "msg-" + Math.floor(1000 + Math.random() * 9000),
      type: "ai",
      content,
      mode,
      sql,
      executionTime: "0.15s",
      execution_time: "0.15s",
      data,
      success: true,
      created_at: new Date().toISOString()
    };
    
    mockAssistantHistoryList.push({
      id: "msg-u-" + Math.floor(1000 + Math.random() * 9000),
      type: "user",
      content: text,
      mode
    } as any);
    mockAssistantHistoryList.push(newMsg as any);
    setStoredItem("vm_mock_assistant_history", mockAssistantHistoryList);
    
    return Promise.resolve(newMsg);
  }

  return apiFetch<AssistantResponse>(`/assistant/query`, {
    method: "POST",
    body: JSON.stringify({
      query_text: text,
      mode: mode,
    }),
  }).then(normalizeAssistantPayload);
}

export function getAssistantHistory(): Promise<AssistantResponse[]> {
  if (USE_MOCK_API) {
    return Promise.resolve(mockAssistantHistoryList.map(normalizeAssistantPayload) as AssistantResponse[]);
  }
  return apiFetch<AssistantResponse[]>("/assistant/history").then((rows) => rows.map(normalizeAssistantPayload));
}

// ── Auth ──────────────────────────────────────────────────────────────────────

const API_BASE_ROOT = API_BASE;

// Mock values for demonstration
const MOCK_MANAGER: User = {
  id: "b0000000-0000-0000-0000-000000000001",
  email: "manager@niletech.com",
  name: "Galal Manager",
  role: "manager",
  organization_id: "a0000000-0000-0000-0000-000000000001",
  is_active: true
};

const MOCK_AGENT: User = {
  id: "b0000001-0000-0000-0000-000000000002",
  email: "agent@niletech.com",
  name: "Mohsen Agent",
  role: "agent",
  agent_type: "human",
  organization_id: "a0000000-0000-0000-0000-000000000001",
  is_active: true
};

let currentUser: User | null = null;

export async function loginWithEmail(email: string, password: string): Promise<{ access_token: string }> {
  // Optional mock mode for UI demos without backend auth.
  if (USE_MOCK_AUTH && password === "Password*8") {
    if (email === "manager@niletech.com") {
      currentUser = MOCK_MANAGER;
      return { access_token: "mock-token-manager" };
    } else if (email === "agent@niletech.com") {
      currentUser = MOCK_AGENT;
      return { access_token: "mock-token-agent" };
    }
  }

  const formData = new URLSearchParams();
  formData.append("username", email);
  formData.append("password", password);

  try {
    const res = await fetch(`${API_BASE_ROOT}/auth/login/access-token`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: formData,
    });

    if (!res.ok) {
      throw new Error("Invalid email or password");
    }

    const data = await res.json();
    persistAccessToken(data.access_token);
    return data;
  } catch (err) {
    if (USE_MOCK_AUTH && password === "Password*8" && (email === "manager@niletech.com" || email === "agent@niletech.com")) {
      currentUser = email === "manager@niletech.com" ? MOCK_MANAGER : MOCK_AGENT;
      persistAccessToken("mock-token-fallback");
      return { access_token: "mock-token-fallback" };
    }
    throw err;
  }
}

export async function loginWithGoogle(idToken: string): Promise<{ access_token: string }> {
  const data = await apiFetch<{ access_token: string }>(`/auth/google?token=${encodeURIComponent(idToken)}`, {
    method: "POST",
  });
  persistAccessToken(data.access_token);
  return data;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: "manager" | "agent";
  agent_type?: "human" | "ai" | null;
  organization_id: string;
  is_active: boolean;
}

export async function getUserMe(): Promise<User> {
  if (USE_MOCK_AUTH) {
    if (!currentUser) {
      currentUser = MOCK_MANAGER; // Default to manager if none is logged in
    }
    return currentUser;
  }
  return apiFetch<User>("/users/me");
}

export async function logoutUser(): Promise<void> {
  if (USE_MOCK_AUTH) {
    currentUser = null;
    clearPersistedAccessToken();
    return Promise.resolve();
  }
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } finally {
    clearPersistedAccessToken();
  }
}
