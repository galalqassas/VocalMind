/**
 * Bundled session export — dashboard aggregates and re-exported interaction records
 * for optional offline/demo frontend mode (VITE_USE_OFFLINE_DEMO=true).
 */

export const bundleDashboardStats = {
  "kpis": {
    "avgScore": 72.4,
    "totalCalls": 18,
    "resolutionRate": 78.0,
    "violationCount": 8
  },
  "weeklyTrend": [
    {
      "day": "Sun",
      "score": 66.0
    },
    {
      "day": "Mon",
      "score": 70.0
    },
    {
      "day": "Tue",
      "score": 58.0
    },
    {
      "day": "Wed",
      "score": 74.0
    },
    {
      "day": "Thu",
      "score": 78.0
    },
    {
      "day": "Sat",
      "score": 79.0
    }
  ],
  "emotionDistribution": [
    {
      "name": "Neutral",
      "value": 47.0,
      "color": "#6B7280"
    },
    {
      "name": "Empathetic",
      "value": 17.0,
      "color": "#8B5CF6"
    },
    {
      "name": "Happy",
      "value": 15.0,
      "color": "#10B981"
    },
    {
      "name": "Frustrated",
      "value": 10.0,
      "color": "#F59E0B"
    },
    {
      "name": "Angry",
      "value": 7.0,
      "color": "#EF4444"
    },
    {
      "name": "Fearful",
      "value": 4.0,
      "color": "#EC4899"
    },
    {
      "name": "Sad",
      "value": 1.0,
      "color": "#3B82F6"
    }
  ],
  "policyCompliance": [
    {
      "category": "Communication",
      "rate": 82.0,
      "color": "#3B82F6"
    },
    {
      "category": "Escalation",
      "rate": 82.0,
      "color": "#3B82F6"
    }
  ],
  "agentPerformance": [
    {
      "name": "Sara Agent",
      "empathy": 83.0,
      "policy": 80.0,
      "resolution": 82.0,
      "overallScore": 79.0,
      "trend": "up"
    },
    {
      "name": "Mohsen Agent",
      "empathy": 72.0,
      "policy": 77.0,
      "resolution": 74.0,
      "overallScore": 76.0,
      "trend": "up"
    },
    {
      "name": "Nour AI Bot",
      "empathy": 72.0,
      "policy": 58.0,
      "resolution": 78.0,
      "overallScore": 70.0,
      "trend": "up"
    },
    {
      "name": "Omar Agent",
      "empathy": 61.0,
      "policy": 57.0,
      "resolution": 66.0,
      "overallScore": 62.0,
      "trend": "up"
    }
  ],
  "interactions": [
    {
      "id": "d0000000-0000-0000-0000-000000000012",
      "agentName": "Nour AI Bot",
      "date": "2026-02-16",
      "time": "09:53 PM",
      "duration": "4:20",
      "language": "en",
      "overallScore": 53.0,
      "empathyScore": 58.0,
      "policyScore": 43.0,
      "resolutionScore": 52.0,
      "resolved": true,
      "hasViolation": false,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000003",
      "agentName": "Omar Agent",
      "date": "2026-02-04",
      "time": "06:26 AM",
      "duration": "5:20",
      "language": "ar",
      "overallScore": 57.0,
      "empathyScore": 47.0,
      "policyScore": 57.0,
      "resolutionScore": 65.0,
      "resolved": true,
      "hasViolation": false,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000001",
      "agentName": "Mohsen Agent",
      "date": "2026-02-01",
      "time": "09:00 AM",
      "duration": "3:00",
      "language": "en",
      "overallScore": 57.0,
      "empathyScore": 71.0,
      "policyScore": 47.0,
      "resolutionScore": 50.0,
      "resolved": false,
      "hasViolation": false,
      "hasOverlap": true
    },
    {
      "id": "d0000000-0000-0000-0000-000000000007",
      "agentName": "Omar Agent",
      "date": "2026-02-10",
      "time": "01:18 AM",
      "duration": "3:30",
      "language": "en",
      "overallScore": 58.0,
      "empathyScore": 43.0,
      "policyScore": 50.0,
      "resolutionScore": 76.0,
      "resolved": true,
      "hasViolation": true,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000014",
      "agentName": "Sara Agent",
      "date": "2026-02-19",
      "time": "07:19 PM",
      "duration": "5:10",
      "language": "ar",
      "overallScore": 58.0,
      "empathyScore": 72.0,
      "policyScore": 54.0,
      "resolutionScore": 50.0,
      "resolved": true,
      "hasViolation": false,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000017",
      "agentName": "Mohsen Agent",
      "date": "2026-02-23",
      "time": "07:28 PM",
      "duration": "4:30",
      "language": "en",
      "overallScore": 61.0,
      "empathyScore": 48.0,
      "policyScore": 70.0,
      "resolutionScore": 52.0,
      "resolved": true,
      "hasViolation": true,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000015",
      "agentName": "Omar Agent",
      "date": "2026-02-21",
      "time": "06:02 AM",
      "duration": "3:15",
      "language": "en",
      "overallScore": 66.0,
      "empathyScore": 78.0,
      "policyScore": 48.0,
      "resolutionScore": 61.0,
      "resolved": true,
      "hasViolation": true,
      "hasOverlap": true
    },
    {
      "id": "d0000000-0000-0000-0000-000000000011",
      "agentName": "Omar Agent",
      "date": "2026-02-15",
      "time": "11:10 AM",
      "duration": "3:40",
      "language": "en",
      "overallScore": 67.0,
      "empathyScore": 77.0,
      "policyScore": 73.0,
      "resolutionScore": 64.0,
      "resolved": false,
      "hasViolation": true,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000006",
      "agentName": "Sara Agent",
      "date": "2026-02-08",
      "time": "02:35 PM",
      "duration": "3:10",
      "language": "ar",
      "overallScore": 70.0,
      "empathyScore": 69.0,
      "policyScore": 72.0,
      "resolutionScore": 80.0,
      "resolved": false,
      "hasViolation": false,
      "hasOverlap": false
    },
    {
      "id": "d0000000-0000-0000-0000-000000000016",
      "agentName": "Nour AI Bot",
      "date": "2026-02-22",
      "time": "04:45 PM",
      "duration": "3:50",
      "language": "ar",
      "overallScore": 71.0,
      "empathyScore": 57.0,
      "policyScore": 61.0,
      "resolutionScore": 81.0,
      "resolved": false,
      "hasViolation": false,
      "hasOverlap": false
    }
  ]
};

export { exportedInteractions, exportedInteractionDetails } from "./processedSessionExport";

export const bundlePolicies = [
  {
    "id": "20000000-0000-0000-0000-000000000006",
    "documentType": "policy",
    "title": "Closing Script",
    "category": "Communication",
    "content": "Agents must summarize the resolution and ask if there is anything else before ending the call.",
    "preview": "Agents must summarize the resolution and ask if there is any...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "20000000-0000-0000-0000-000000000004",
    "documentType": "policy",
    "title": "Data Privacy Compliance",
    "category": "Privacy",
    "content": "Agents must never ask for full credit card numbers or passwords over the phone.",
    "preview": "Agents must never ask for full credit card numbers or passwo...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "20000000-0000-0000-0000-000000000002",
    "documentType": "policy",
    "title": "Escalation Protocol",
    "category": "Escalation",
    "content": "If a customer expresses extreme frustration or anger, the agent must offer to escalate to a supervisor within 60 seconds.",
    "preview": "If a customer expresses extreme frustration or anger, the ag...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 30
  },
  {
    "id": "20000000-0000-0000-0000-000000000001",
    "documentType": "policy",
    "title": "Greeting Policy",
    "category": "Communication",
    "content": "Agents must greet customers warmly and professionally within the first 5 seconds of the call.",
    "preview": "Agents must greet customers warmly and professionally within...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 30
  },
  {
    "id": "20000000-0000-0000-0000-000000000003",
    "documentType": "policy",
    "title": "Hold Time Limit",
    "category": "Communication",
    "content": "Customers must not be placed on hold for more than 2 minutes without a status update.",
    "preview": "Customers must not be placed on hold for more than 2 minutes...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 10
  },
  {
    "id": "20000000-0000-0000-0000-000000000005",
    "documentType": "policy",
    "title": "Refund Authorization",
    "category": "Finance",
    "content": "Agents may authorize refunds up to $50 without supervisor approval. Amounts above $50 require escalation.",
    "preview": "Agents may authorize refunds up to $50 without supervisor ap...",
    "lastUpdated": "2026-06-01",
    "isActive": true,
    "usageCount": 0
  }
];

export const bundleFaqs = [
  {
    "id": "f0000000-0000-0000-0000-000000000007",
    "documentType": "faq",
    "question": "How do I cancel my subscription?",
    "answer": "Go to Settings > Subscription > Cancel. Note: cancellation takes effect at the end of the billing cycle.",
    "preview": "Go to Settings > Subscription > Cancel. Note: cancellation t...",
    "category": "Billing",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000004",
    "documentType": "faq",
    "question": "How do I contact technical support?",
    "answer": "Use the in-app chat, call +1-800-555-0199, or email support@vocalmind.com.",
    "preview": "Use the in-app chat, call +1-800-555-0199, or email support@...",
    "category": "Technical",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000001",
    "documentType": "faq",
    "question": "How do I reset my password?",
    "answer": "Go to Settings > Security > Reset Password, or click 'Forgot password' on the login page.",
    "preview": "Go to Settings > Security > Reset Password, or click 'Forgot...",
    "category": "Account",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000002",
    "documentType": "faq",
    "question": "How do I update my billing information?",
    "answer": "Navigate to Settings > Billing > Payment Methods and update your card details.",
    "preview": "Navigate to Settings > Billing > Payment Methods and update ...",
    "category": "Billing",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000005",
    "documentType": "faq",
    "question": "How to enable two-factor authentication?",
    "answer": "Go to Settings > Security > 2FA and follow the setup wizard with your authenticator app.",
    "preview": "Go to Settings > Security > 2FA and follow the setup wizard ...",
    "category": "Account",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000008",
    "documentType": "faq",
    "question": "How to export my data?",
    "answer": "Navigate to Settings > Data Management > Export. You can download CSV or JSON formats.",
    "preview": "Navigate to Settings > Data Management > Export. You can dow...",
    "category": "Technical",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000006",
    "documentType": "faq",
    "question": "What are the service hours?",
    "answer": "Our support team is available 24/7 for critical issues. General inquiries: Sun-Thu 9AM-6PM EET.",
    "preview": "Our support team is available 24/7 for critical issues. Gene...",
    "category": "General",
    "isActive": true,
    "usageCount": 0
  },
  {
    "id": "f0000000-0000-0000-0000-000000000003",
    "documentType": "faq",
    "question": "What is the refund policy?",
    "answer": "Refunds are processed within 5-7 business days. Contact support for amounts over $50.",
    "preview": "Refunds are processed within 5-7 business days. Contact supp...",
    "category": "Billing",
    "isActive": true,
    "usageCount": 0
  }
];

export const bundleKb = [];

export const bundleAgents = [
  {
    "id": "b0000000-0000-0000-0000-000000000002",
    "name": "Mohsen Agent",
    "role": "agent"
  },
  {
    "id": "b0000000-0000-0000-0000-000000000003",
    "name": "Sara Agent",
    "role": "agent"
  },
  {
    "id": "b0000000-0000-0000-0000-000000000004",
    "name": "Omar Agent",
    "role": "agent"
  },
  {
    "id": "b0000000-0000-0000-0000-000000000005",
    "name": "Nour AI Bot",
    "role": "agent"
  }
];

export const bundleAssistantHistory = [
  {
    "id": "q_33000000-0000-0000-0000-000000000008",
    "type": "user",
    "content": "Compare agent performance this month.",
    "mode": "chat",
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "a_33000000-0000-0000-0000-000000000008",
    "type": "ai",
    "content": "Mohsen: 8.5 avg, Sara: 9.2 avg, Omar: 7.8 avg, Nour AI: 8.9 avg.",
    "mode": "chat",
    "success": false,
    "sql": null,
    "executionTime": null,
    "execution_time": null,
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "q_33000000-0000-0000-0000-000000000006",
    "type": "user",
    "content": "List the most common customer emotions.",
    "mode": "chat",
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "a_33000000-0000-0000-0000-000000000006",
    "type": "ai",
    "content": "The most common emotions are: neutral (35%), frustrated (25%), happy (20%), angry (10%), and others (10%).",
    "mode": "chat",
    "success": false,
    "sql": null,
    "executionTime": null,
    "execution_time": null,
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "q_33000000-0000-0000-0000-000000000004",
    "type": "user",
    "content": "What is the resolution rate?",
    "mode": "chat",
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "a_33000000-0000-0000-0000-000000000004",
    "type": "ai",
    "content": "The current resolution rate is 80% across all agents.",
    "mode": "chat",
    "success": false,
    "sql": null,
    "executionTime": null,
    "execution_time": null,
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "q_33000000-0000-0000-0000-000000000002",
    "type": "user",
    "content": "Which agent has the highest score this week?",
    "mode": "chat",
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "a_33000000-0000-0000-0000-000000000002",
    "type": "ai",
    "content": "Sara Agent has the highest average score of 92 this week.",
    "mode": "chat",
    "success": false,
    "sql": null,
    "executionTime": null,
    "execution_time": null,
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "q_33000000-0000-0000-0000-000000000001",
    "type": "user",
    "content": "How many calls were handled today?",
    "mode": "chat",
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  },
  {
    "id": "a_33000000-0000-0000-0000-000000000001",
    "type": "ai",
    "content": "There were 5 calls handled today with an average score of 8.2.",
    "mode": "chat",
    "success": false,
    "sql": null,
    "executionTime": null,
    "execution_time": null,
    "created_at": "2026-06-01T09:29:05.129568+00:00"
  }
];
