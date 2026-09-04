import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/lib/auth";

// Cast once, locally, instead of scattering `as any` at every call site.
const mockFetch = () => fetch as unknown as ReturnType<typeof vi.fn>;

// api.ts reads NEXT_PUBLIC_API_URL at module-load time, so it must be set
// before the module is imported. Each test re-imports it fresh via
// vi.resetModules() to get a clean `request` closure and a clean mock.
async function loadApi() {
  const mod = await import("@/lib/api");
  return mod;
}

describe("api request layer", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    // jsdom throws on unhandled navigation; stub it out and just record it.
    Object.defineProperty(window, "location", {
      value: { ...window.location, href: "", pathname: "/" },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the bearer token to authenticated requests", async () => {
    setToken("test-token-123");
    mockFetch().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });

    const { api } = await loadApi();
    await api.listWatchlist();

    const [, init] = mockFetch().mock.calls[0];
    expect(init.headers["Authorization"]).toBe("Bearer test-token-123");
  });

  it("does not attach a token to signup/login requests", async () => {
    setToken("test-token-123");
    mockFetch().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: "new-token", token_type: "bearer" }),
    });

    const { api } = await loadApi();
    await api.login("user@example.com", "password123");

    const [, init] = mockFetch().mock.calls[0];
    expect(init.headers["Authorization"]).toBeUndefined();
  });

  it("stores the returned token after a successful login", async () => {
    mockFetch().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: "fresh-token", token_type: "bearer" }),
    });

    const { api } = await loadApi();
    await api.login("user@example.com", "password123");

    const { getToken } = await import("@/lib/auth");
    expect(getToken()).toBe("fresh-token");
  });

  it("throws ApiError with the server-provided detail message on failure", async () => {
    mockFetch().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Incorrect email or password." }),
    });

    const { api, ApiError } = await loadApi();
    await expect(api.login("user@example.com", "wrong")).rejects.toMatchObject({
      status: 401,
      message: "Incorrect email or password.",
    });
    await expect(api.login("user@example.com", "wrong")).rejects.toBeInstanceOf(ApiError);
  });

  it("clears the token and redirects on a 401 from a non-auth endpoint", async () => {
    setToken("stale-token");
    mockFetch().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Invalid or expired token." }),
    });

    const { api } = await loadApi();
    await expect(api.listWatchlist()).rejects.toBeTruthy();

    const { getToken } = await import("@/lib/auth");
    expect(getToken()).toBeNull();
    expect(window.location.href).toBe("/login");
  });

  it("does not clear the token on a 401 from the login endpoint itself", async () => {
    setToken("still-valid-token");
    mockFetch().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Incorrect email or password." }),
    });

    const { api } = await loadApi();
    await expect(api.login("user@example.com", "wrong")).rejects.toBeTruthy();

    const { getToken } = await import("@/lib/auth");
    expect(getToken()).toBe("still-valid-token");
  });

  it("returns undefined for 204 No Content responses", async () => {
    setToken("test-token");
    mockFetch().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("should not be called for 204");
      },
    });

    const { api } = await loadApi();
    await expect(api.removeTicker("AAPL")).resolves.toBeUndefined();
  });
});
