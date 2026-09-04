"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { AuthForm } from "@/components/Authform";

export default function SignupPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(email: string, password: string) {
    setSubmitting(true);
    setError(null);
    try {
      await api.signup(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex-1 flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight mb-1">Create account</h1>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Start tracking what deserves your attention.
        </p>
        <AuthForm mode="signup" onSubmit={handleSubmit} submitting={submitting} error={error} />
        <p className="text-xs text-[var(--text-tertiary)] mt-6">
          Already have an account?{" "}
          <Link href="/login" className="text-[var(--text-primary)] underline">
            Log in
          </Link>
        </p>
      </div>
    </main>
  );
}
