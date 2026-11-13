"use client";

import { useCallback, useEffect, useState } from "react";
import { StaffTopbar } from "@/components/Brand";
import { TwoFactorSection } from "@/components/TwoFactor";
import { api } from "@/lib/api";
import { useStaff } from "@/lib/useStaff";

type StaffRow = { id: number; name: string; email: string; role: string; active: boolean; two_factor: boolean };

export default function Account() {
  const { me, signOut } = useStaff();
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const [staff, setStaff] = useState<StaffRow[]>([]);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "reception" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const isAdmin = me?.role === "admin";
  const [twoFactor, setTwoFactor] = useState<boolean | null>(null);
  const twoFactorOn = twoFactor ?? me?.two_factor ?? false;

  const loadStaff = useCallback(() => {
    api<StaffRow[]>("/api/staff/staff").then(setStaff).catch(() => {});
  }, []);

  useEffect(() => {
    if (isAdmin) loadStaff();
  }, [isAdmin, loadStaff]);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/staff/me/password", { body: pw });
      setPw({ current_password: "", new_password: "" });
      setPwMsg({ ok: true, text: "Password changed." });
    } catch (err) {
      setPwMsg({ ok: false, text: (err as Error).message });
    }
  }

  async function addStaff(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/staff/staff", { body: form });
      setMsg({ ok: true, text: `Account created for ${form.name}. Give them the password in person, not by SMS.` });
      setForm({ name: "", email: "", password: "", role: "reception" });
      loadStaff();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  }

  async function update(s: StaffRow, body: Record<string, unknown>, done: string) {
    try {
      await api(`/api/staff/staff/${s.id}`, { method: "PATCH", body });
      setMsg({ ok: true, text: done });
      loadStaff();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  }

  function resetPassword(s: StaffRow) {
    const pwd = window.prompt(`New password for ${s.name} (at least 10 characters):`);
    if (pwd) update(s, { password: pwd }, `Password reset for ${s.name}. They have been signed out.`);
  }

  return (
    <>
      <StaffTopbar labName={me?.lab.name} active="account" onSignOut={signOut} isAdmin={isAdmin} />
      <main className="lab-main">
        <section className="card stack col-side" aria-labelledby="pw-title">
          <h1 id="pw-title" style={{ fontSize: 20 }}>My account</h1>
          <p className="small muted">{me?.name} · {me?.email} · {me?.role}</p>
          <form className="stack" onSubmit={changePassword}>
            <label className="stack" style={{ gap: 4 }}>
              <span className="label">Current password</span>
              <input className="input" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <span className="label">New password (10+ characters)</span>
              <input className="input" type="password" autoComplete="new-password" minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required />
            </label>
            {pwMsg && <p className={pwMsg.ok ? "ok small" : "error small"} role="status">{pwMsg.text}</p>}
            <button className="btn btn-primary">Change password</button>
          </form>
          {me && <TwoFactorSection enabled={twoFactorOn} onChange={(on) => { setTwoFactor(on); if (isAdmin) loadStaff(); }} />}
        </section>

        {isAdmin && (
          <section className="card stack col-main" aria-labelledby="staff-title">
            <h2 id="staff-title" style={{ fontSize: 20 }}>Staff accounts</h2>
            <div style={{ overflowX: "auto" }}>
              <table style={{ minWidth: 600 }}>
                <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Two-step</th><th></th></tr></thead>
                <tbody>
                  {staff.map((s) => (
                    <tr key={s.id}>
                      <td><b>{s.name}</b></td>
                      <td className="small">{s.email}</td>
                      <td className="small">{s.role}</td>
                      <td>{s.active ? <span className="pill pill-opened">Active</span> : <span className="pill pill-sent">Disabled</span>}</td>
                      <td className="small">{s.two_factor ? "On" : "Off"}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {s.id !== me?.id && (
                          <>
                            <button className="btn-link small" onClick={() => resetPassword(s)}>Reset password</button>
                            {s.two_factor && (
                              <button className="btn-link small" onClick={() => window.confirm(`Turn off two-step sign-in for ${s.name} (for a lost phone)? They will be signed out.`) && update(s, { reset_two_factor: true }, `Two-step sign-in reset for ${s.name}. They can sign in with their password and set it up again.`)}>
                                Reset two-step
                              </button>
                            )}
                            <button className="btn-link small" onClick={() => update(s, { active: !s.active }, s.active ? `${s.name} disabled and signed out.` : `${s.name} enabled.`)}>
                              {s.active ? "Disable" : "Enable"}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <form className="stack" onSubmit={addStaff} style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
              <b>Add a staff member</b>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <label className="stack" style={{ gap: 4, flex: "1 1 180px" }}>
                  <span className="label">Name</span>
                  <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                </label>
                <label className="stack" style={{ gap: 4, flex: "1 1 220px" }}>
                  <span className="label">Email</span>
                  <input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
                </label>
                <label className="stack" style={{ gap: 4, flex: "1 1 180px" }}>
                  <span className="label">Starting password</span>
                  <input className="input" type="text" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
                </label>
                <label className="stack" style={{ gap: 4, flex: "0 1 150px" }}>
                  <span className="label">Role</span>
                  <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                    <option value="reception">Reception</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
              </div>
              {msg && <p className={msg.ok ? "ok small" : "error small"} role="status">{msg.text}</p>}
              <button className="btn btn-primary" style={{ alignSelf: "flex-start" }}>Add staff member</button>
            </form>
          </section>
        )}
      </main>
    </>
  );
}
