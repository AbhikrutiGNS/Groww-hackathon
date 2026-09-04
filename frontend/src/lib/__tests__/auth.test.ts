import { beforeEach, describe, expect, it } from "vitest";
import { clearToken, getToken, setToken } from "@/lib/auth";

describe("auth token storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns null when no token has been set", () => {
    expect(getToken()).toBeNull();
  });

  it("returns the token that was set", () => {
    setToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
  });

  it("overwrites a previously stored token", () => {
    setToken("first-token");
    setToken("second-token");
    expect(getToken()).toBe("second-token");
  });

  it("clears the stored token", () => {
    setToken("some-token");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
