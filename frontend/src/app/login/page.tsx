"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(username, password);
      if ("access_token" in (result as object)) {
        throw new Error("Login response included a forbidden access token.");
      }
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <p className="text-xs uppercase tracking-wide text-navy-mid">Ministry of Health Uganda</p>
      <h1 className="mt-2 text-2xl font-semibold">Health Performance Intelligence</h1>
      <p className="mt-2 text-sm text-slate-600">
        Sign in with a cookie-only session. Tokens are not stored in the browser.
      </p>
      <form onSubmit={onSubmit} className="mt-8 space-y-4 rounded-xl border border-line bg-white p-6">
        <label className="block text-sm font-medium">
          Username
          <input
            className="mt-1 w-full rounded-md border border-line px-3 py-2"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            type="password"
            className="mt-1 w-full rounded-md border border-line px-3 py-2"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button type="submit" disabled={busy} className="w-full rounded-md bg-navy px-4 py-2 text-white disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
