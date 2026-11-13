"use client";

import { useState } from "react";
import { QrCode } from "@/components/QrCode";
import { api } from "@/lib/api";

// Turn two-step sign-in on or off for the signed-in staff member.
export function TwoFactorSection({ enabled, onChange }: { enabled: boolean; onChange: (on: boolean) => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function start() {
    setMsg(null);
    try {
      setSetup(await api("/api/staff/me/2fa/setup", { method: "POST" }));
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/staff/me/2fa/enable", { body: { code } });
      setSetup(null);
      setCode("");
      setMsg({ ok: true, text: "Two-step sign-in is on. You will need the app's code each time you sign in." });
      onChange(true);
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  }

  async function turnOff(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/staff/me/2fa/disable", { body: { password, code } });
      setPassword("");
      setCode("");
      setMsg({ ok: true, text: "Two-step sign-in is off." });
      onChange(false);
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <div className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>Two-step sign-in</b>
        <span className={`pill ${enabled ? "pill-opened" : "pill-sent"}`}>{enabled ? "On" : "Off"}</span>
      </div>
      <p className="small muted">
        After your password, you also type a code from an authenticator app on your phone (Google Authenticator or
        Microsoft Authenticator). Strongly recommended for lab admins.
      </p>

      {!enabled && !setup && <button className="btn" onClick={start}>Set up two-step sign-in</button>}

      {!enabled && setup && (
        <form className="stack" onSubmit={confirm}>
          <ol className="small" style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            <li>Install an authenticator app on your phone.</li>
            <li>In the app, add an account and scan this QR code.</li>
            <li>Type the 6-digit code the app shows.</li>
          </ol>
          <QrCode value={setup.otpauth_uri} size={180} label="QR code for the authenticator app" />
          <p className="tiny muted" style={{ wordBreak: "break-all" }}>Can&apos;t scan? Type this key in the app: <b>{setup.secret}</b></p>
          <input className="input code-input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} aria-label="Code from the app"
                 value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <button className="btn btn-primary" disabled={code.length !== 6}>Turn on</button>
        </form>
      )}

      {enabled && (
        <form className="stack" onSubmit={turnOff}>
          <span className="small">To turn it off, enter your password and a current code.</span>
          <input className="input" type="password" autoComplete="current-password" aria-label="Password" placeholder="Password"
                 value={password} onChange={(e) => setPassword(e.target.value)} required />
          <input className="input" inputMode="numeric" maxLength={6} aria-label="Code from the app" placeholder="6-digit code"
                 value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
          <button className="btn danger-btn" disabled={code.length !== 6}>Turn off</button>
        </form>
      )}
      {msg && <p className={msg.ok ? "ok small" : "error small"} role="status">{msg.text}</p>}
    </div>
  );
}
