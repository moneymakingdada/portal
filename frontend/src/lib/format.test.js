import { describe, expect, it } from "vitest";
import { ghs, pluralize, signedGhs } from "./format";

describe("ghs", () => {
  it("formats pesewas as cedis", () => {
    expect(ghs(250)).toBe("GH\u20b52.50");
    expect(ghs(0)).toBe("GH\u20b50.00");
    expect(ghs(5)).toBe("GH\u20b50.05");
  });
  it("treats missing input as zero", () => {
    expect(ghs(undefined)).toBe("GH\u20b50.00");
  });
});

describe("signedGhs", () => {
  it("prefixes credits with + and debits with a minus sign", () => {
    expect(signedGhs(500)).toBe("+GH\u20b55.00");
    expect(signedGhs(-500)).toBe("\u2212GH\u20b55.00");
  });
});

describe("pluralize", () => {
  it("chooses singular or plural", () => {
    expect(pluralize(1, "message")).toBe("1 message");
    expect(pluralize(0, "message")).toBe("0 messages");
    expect(pluralize(5, "message")).toBe("5 messages");
    expect(pluralize(2, "child", "children")).toBe("2 children");
  });
});
