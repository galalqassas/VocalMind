import { describe, expect, it } from "vitest";
import {
  parseTimestampLabel,
  resolveJumpSeconds,
} from "../app/utils/utteranceNavigation";
import { stripRedundantEvidenceNarrative, uniqueByQuote } from "../app/utils/evidenceDisplay";

describe("utteranceNavigation jump helpers", () => {
  const utterances = [
    { id: "1", sequenceIndex: 0, startTime: 260, timestamp: "04:20", text: "hello" },
    { id: "2", sequenceIndex: 1, startTime: 300, timestamp: "05:00", text: "world" },
  ] as any[];

  it("parses mm:ss timestamps", () => {
    expect(parseTimestampLabel("04:20")).toBe(260);
    expect(parseTimestampLabel("5:00")).toBe(300);
  });

  it("resolves jump seconds from timestamp when startSeconds missing", () => {
    expect(resolveJumpSeconds(utterances, { timestamp: "04:20" })).toBe(260);
  });

  it("prefers explicit startSeconds", () => {
    expect(resolveJumpSeconds(utterances, { startSeconds: 12, timestamp: "04:20" })).toBe(12);
  });
});

describe("evidenceDisplay", () => {
  it("strips trailing inline evidence when citations exist", () => {
    const text = "Customer became frustrated. Evidence: \"I have waited forever\"";
    expect(stripRedundantEvidenceNarrative(text, true)).toBe("Customer became frustrated.");
  });

  it("deduplicates citations by quote", () => {
    const items = [
      { quote: "Same quote" },
      { quote: "Same quote" },
      { quote: "Different" },
    ];
    expect(uniqueByQuote(items)).toHaveLength(2);
  });
});
