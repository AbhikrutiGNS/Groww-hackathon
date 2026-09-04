"use client";

import { useState } from "react";

export function AuthForm({
  mode,
  onSubmit,
  submitting,
  error,
}: {
  mode: "login" | "signup";
  onSubmit: (email: string, password: string) => void;
  submitting: boolean;
  error: string | null;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    onSubmit(email.trim(), password);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className="block text-xs text-[var(--text-secondary)] mb-1.5" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-raised)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--signal)]"
        />
      </div>

      <div>
        <label className="block text-xs text-[var(--text-secondary)] mb-1.5" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "signup" ? 8 : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
          className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-raised)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--signal)]"
        />
      </div>

      {error && <p className="text-xs text-[var(--loss)]">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !email.trim() || !password}
        className="rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 transition-colors"
        style={{ background: "var(--signal)", color: "#1a1305" }}
      >
        {submitting
          ? mode === "login"
            ? "Logging in…"
            : "Creating account…"
          : mode === "login"
          ? "Log in"
          : "Create account"}
      </button>
    </form>
  );
}