"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BrandMark } from "@/components/Brand";
import { api } from "@/lib/api";

export default function StaffLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/staff/login", { body: { email, password, code: needCode ? code : undefined } });
      router.push("/staff");
    } catch (err) {
      const msg = (err as Error).message;
      if (msg === "two_factor_required") {
        setNeedCode(true); // password was right; now ask for the authenticator code
      } else {
        setError(msg);
        setCode("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="phone-shell" style={{ justifyContent: "center", padding: 24 }}>
      <form className="card stack" onSubmit={submit} style={{ gap: 16 }}>
        <div className="row" style={{ gap: 10 }}>
          <BrandMark />
          <h1 style={{ fontSize: 22 }}>Lab staff sign in</h1>
        </div>
        {!needCode ? (
          <>
            <label className="stack" style={{ gap: 6 }}>
              <span className="label">Email</span>
              <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="stack" style={{ gap: 6 }}>
              <span className="label">Password</span>
              <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
          </>
        ) : (
          <label className="stack" style={{ gap: 6 }}>
            <span className="label">6-digit code from your authenticator app</span>
            <input className="input code-input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus
                   value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
            <span className="tiny muted">Lost your phone? Ask your lab admin to reset two-step sign-in.</span>
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn-primary btn-big" disabled={busy || (needCode && code.length !== 6)}>
          {busy ? "Signing in…" : needCode ? "Confirm" : "Sign in"}
        </button>
        {needCode && (
          <button type="button" className="btn-link small" onClick={() => { setNeedCode(false); setCode(""); setPassword(""); }}>
            Use a different account
          </button>
        )}
      </form>
    </main>
  );
}
