import { buildInteractionDetail, buildInteractionSummary } from '../support/e2eApiFixtures';

describe("Session Detail", () => {
  beforeEach(() => {
    // Intercept audio fetch to resolve instantly so the player renders
    cy.intercept('GET', '**/api/v1/interactions/*/audio', {
      statusCode: 200,
      body: new Blob([''], { type: 'audio/wav' }),
    }).as('getAudio');

    cy.visitAs("manager", "/manager/inspector/int-001", {
      interactionDetails: {
        'int-001': {
          body: buildInteractionDetail(buildInteractionSummary(), {
            emotionComparison: { 
              totalUtterances: 5,
              distributions: { acoustic: [], text: [], fused: [] },
              quality: { acousticTextAgreementRate: 0, fusedMatchesAcousticRate: 0, fusedMatchesTextRate: 0, disagreementCount: 0 }
            } as any, // Triggers hasEmotion
            policyViolations: [{ id: '1', policyName: 'Test' } as any], // Triggers hasViolations
            ragCompliance: { available: true } as any, // Triggers hasRag
          })
        }
      }
    });
  });

  it("renders the back navigation link", () => {
    cy.contains("a", "Back to Session Inspector")
      .should("have.attr", "href", "/manager/inspector");
  });

  it("displays agent name and call metadata", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("h2", "Sarah M.");
    cy.contains(/english/i);
    cy.contains("2025-03-01");
    cy.contains("09:15 AM");
  });

  it("displays the score grid with four categories", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("Empathy");
    cy.contains("Policy");
    cy.contains("Resolution");
    cy.contains("Resp. Time");
  });

  it("renders the AnalysisTabs with correct tabs", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("button", "Emotion").should("exist");
    cy.contains("button", "Process").should("exist");
    cy.contains("button", "Policy").should("exist");
    cy.contains("button", "Quality").should("exist");
  });

  it("renders the audio player", () => {
    cy.wait('@getAudio');
    cy.get('audio').should('exist');
    cy.get('svg.lucide-play, svg.lucide-pause').should('exist');
  });

  it("renders the transcript section with utterances", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("h3", "Transcript").scrollIntoView().should("be.visible");
    cy.contains("Good morning! Thank you for calling VocalMind support.").should("exist");
    cy.contains("Hi, I've been having issues with my account login").should("exist");
  });

  it("renders emotion timeline section", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("h3", "Emotion Timeline").should("be.visible");
  });

  it("renders the dispute flow under the Policy tab", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("button", "Policy").click();
    cy.contains("button", "Dispute").first().click();
    cy.contains("Accurate?").should("be.visible");
    cy.contains("button", "Yes").should("be.visible");
    cy.contains("button", "No").should("be.visible");
  });

  it("navigates back to session inspector", () => {
    cy.wait('@getInteractionDetail');
    cy.contains("a", "Back to Session Inspector").click();
    cy.url().should("include", "/manager/inspector");
    cy.url().should("not.include", "/int-001");
  });

  it("renders Evidence-Anchored Explainability with tabs and badges", () => {
    // Visit with E2E fixture data containing explainability
    cy.visitAs("manager", "/manager/inspector/int-002", {
      interactionDetails: {
        'int-002': {
          body: buildInteractionDetail(buildInteractionSummary(), {
            emotionComparison: { 
              totalUtterances: 5,
              distributions: { acoustic: [], text: [], fused: [] },
              quality: { acousticTextAgreementRate: 0, fusedMatchesAcousticRate: 0, fusedMatchesTextRate: 0, disagreementCount: 0 }
            } as any, // Triggers hasEmotion
            llmTriggers: {
              available: true,
              explainability: {
                triggerAttributions: [
                  {
                    attributionId: "attr-1",
                    triggerType: "policy_finding",
                    title: "Missing Identity Verification",
                    reasoning: "Agent did not verify account.",
                    verdict: "Supported",
                    family: "policy",
                    evidenceChain: [],
                    supportingQuotes: [],
                  },
                  {
                    attributionId: "attr-2",
                    triggerType: "cross_modal_fusion",
                    title: "Text/Acoustic Mismatch",
                    reasoning: "Customer sounded angry but text was neutral.",
                    verdict: "Cross-Modal Mismatch",
                    family: "emotion",
                    evidenceChain: [],
                    supportingQuotes: [],
                  }
                ],
                claimProvenance: []
              }
            } as any
          })
        }
      }
    });

    cy.wait('@getInteractionDetail');

    // Panel title
    cy.contains("Evidence-Anchored Explainability").scrollIntoView().should("be.visible");
    cy.contains("h3", "Claim to evidence to verdict").should("be.visible");

    // Check tabs
    cy.contains("button", "Policy Findings").should("be.visible");
    cy.contains("button", "Span-Level Trigger Attribution").should("be.visible");

    // Check verdicts
    cy.contains("Supported").should("be.visible");
    
    // Switch to Emotion tab to see Cross-Modal Mismatch
    cy.contains("button", "Span-Level Trigger Attribution").click();
    cy.contains("Cross-Modal Mismatch").should("be.visible");
  });
});
