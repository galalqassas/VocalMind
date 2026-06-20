import { describe, expect, it } from "vitest";
import { getDashboardPathForRole, isPathAllowedForRole } from "../app/utils/authRouting";

describe("authRouting", () => {
  it("maps roles to dashboard paths", () => {
    expect(getDashboardPathForRole("manager")).toBe("/manager");
    expect(getDashboardPathForRole("agent")).toBe("/agent");
    expect(getDashboardPathForRole(null)).toBe("/");
  });

  it("allows only same-role route prefixes", () => {
    expect(isPathAllowedForRole("/manager/inspector", "manager")).toBe(true);
    expect(isPathAllowedForRole("/agent/calls", "agent")).toBe(true);
    expect(isPathAllowedForRole("/manager", "agent")).toBe(false);
    expect(isPathAllowedForRole("/agent", "manager")).toBe(false);
  });
});
