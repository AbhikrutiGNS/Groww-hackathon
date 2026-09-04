import { describe, expect, it } from "vitest";
import {
  formatMarketCap,
  formatPercent,
  formatPlainPercent,
  formatPrice,
  formatRatio,
  timeAgo,
} from "@/lib/format";

describe("formatPrice", () => {
  it("renders an em dash for null", () => {
    expect(formatPrice(null)).toBe("—");
  });

  it("renders an em dash for non-numeric input", () => {
    expect(formatPrice("not-a-number")).toBe("—");
  });

  it("formats to two decimal places with thousands separators", () => {
    expect(formatPrice("1234.5")).toBe("1,234.50");
  });

  it("formats a whole number with two decimal places", () => {
    expect(formatPrice("7")).toBe("7.00");
  });
});

describe("formatPercent", () => {
  it("renders an em dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });

  it("prefixes positive values with a plus sign", () => {
    expect(formatPercent("3.456")).toBe("+3.46%");
  });

  it("does not add a plus sign for negative values", () => {
    expect(formatPercent("-2.5")).toBe("-2.50%");
  });

  it("does not add a plus sign for exactly zero", () => {
    expect(formatPercent("0")).toBe("0.00%");
  });
});

describe("formatPlainPercent", () => {
  it("never adds a sign, even for positive values", () => {
    expect(formatPlainPercent("3.456")).toBe("3.46%");
  });

  it("renders an em dash for null", () => {
    expect(formatPlainPercent(null)).toBe("—");
  });
});

describe("formatMarketCap", () => {
  it("renders an em dash for null", () => {
    expect(formatMarketCap(null)).toBe("—");
  });

  it("formats trillions", () => {
    expect(formatMarketCap(String(2.3e12))).toBe("$2.30T");
  });

  it("formats billions", () => {
    expect(formatMarketCap(String(45e9))).toBe("$45.00B");
  });

  it("formats millions", () => {
    expect(formatMarketCap(String(6.7e6))).toBe("$6.70M");
  });

  it("formats thousands", () => {
    expect(formatMarketCap(String(1500))).toBe("$1.50K");
  });

  it("formats sub-thousand values as plain dollars", () => {
    expect(formatMarketCap("500")).toBe("$500.00");
  });
});

describe("formatRatio", () => {
  it("renders an em dash for null", () => {
    expect(formatRatio(null)).toBe("—");
  });

  it("defaults to the × suffix", () => {
    expect(formatRatio("15.678")).toBe("15.68×");
  });

  it("accepts a custom suffix", () => {
    expect(formatRatio("15.678", "x")).toBe("15.68x");
  });
});

describe("timeAgo", () => {
  it("reports 'just now' for timestamps under a minute old", () => {
    const now = new Date().toISOString();
    expect(timeAgo(now)).toBe("just now");
  });

  it("reports minutes for timestamps under an hour old", () => {
    const tenMinutesAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    expect(timeAgo(tenMinutesAgo)).toBe("10m ago");
  });

  it("reports hours for timestamps under a day old", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    expect(timeAgo(threeHoursAgo)).toBe("3h ago");
  });

  it("reports days for timestamps a day or more old", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    expect(timeAgo(twoDaysAgo)).toBe("2d ago");
  });
});
