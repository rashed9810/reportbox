"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { StaffTopbar } from "@/components/Brand";
import { api } from "@/lib/api";
import { bdt, monthName } from "@/lib/money";
import { useStaff } from "@/lib/useStaff";

type Dash = {
  month: string;
  reports_sent: number;
  reports_opened: number;
  open_rate: number | null;
  reminders_sent: number;
  patients_returned: number;
  doctor_shares: number;
  messages: { used: number; quota: number; by_kind: Record<string, number>; by_channel: Record<string, number> };
  reports_quota: number;
  plan_name: string;
  unpaid_invoice: { id: number; period: string; total_paisa: number; due_date: string; status: string } | null;
  upcoming_reminders: { test_code: string; name: string; count: number }[];
};

const KIND_LABEL: Record<string, string> = { report_ready: "\"Report ready\" messages", otp: "Login codes", recall: "Repeat-test reminders" };

export default function Dashboard() {
  const { me, signOut } = useStaff();
  const [d, setD] = useState<Dash | null>(null);
  const [msg, setMsg] = useState("");

  function load() {
    api<Dash>("/api/staff/dashboard").then(setD).catch((e) => setMsg(e.message));
  }
  useEffect(() => {
    if (me) load();
  }, [me]);

  async function runReminders() {
    try {
      const r = await api<{ sent: number }>("/api/staff/recalls/run", { method: "POST" });
      setMsg(`Sent ${r.sent} reminder${r.sent === 1 ? "" : "s"} that were due.`);
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  const usedPct = d ? Math.min(100, Math.round((d.messages.used / Math.max(1, d.messages.quota)) * 100)) : 0;

  return (
    <>
      <StaffTopbar labName={me?.lab.name} active="dashboard" onSignOut={signOut} isAdmin={me?.role === "admin"} />
      <main style={{ maxWidth: 1240, margin: "0 auto", padding: 24 }} className="stack">
        {!d ? (
          <p className="muted">{msg || "Loading…"}</p>
        ) : (
          <>
            {d.unpaid_invoice && me?.role === "admin" && (
              <div className="banner" role="status">
                <span>
                  <b>{monthName(d.unpaid_invoice.period)} bill: {bdt(d.unpaid_invoice.total_paisa)}</b>{" "}
                  {d.unpaid_invoice.status === "overdue" ? "is overdue" : `due ${new Date(d.unpaid_invoice.due_date + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`}
                </span>
                <Link href="/staff/billing" className="btn">Pay now</Link>
              </div>
            )}
            <div className="stack" style={{ gap: 4 }}>
              <h1 style={{ fontSize: 28 }}>
                {d.patients_returned > 0
                  ? `Reminders brought back ${d.patients_returned} patient${d.patients_returned === 1 ? "" : "s"}`
                  : "Your ReportBox month"}
              </h1>
              <p className="muted">Month {d.month}. A patient counts as &ldquo;back&rdquo; when they repeat the test within 60 days of the reminder.</p>
            </div>

            <div className="stats">
              <div className="stat" style={{ background: "var(--amber-tint)", border: "none" }}>
                <div className="small">Patients back after reminder</div>
                <div className="stat-num" style={{ color: "var(--amber)" }}>{d.patients_returned}</div>
                <div className="tiny muted">from {d.reminders_sent} reminders sent</div>
              </div>
              <div className="stat">
                <div className="small">Reports sent</div>
                <div className="stat-num">{d.reports_sent.toLocaleString()}</div>
                <div className="tiny muted">of {d.reports_quota.toLocaleString()} in the {d.plan_name} plan</div>
              </div>
              <div className="stat">
                <div className="small">Opened by patients</div>
                <div className="stat-num" style={{ color: "var(--primary)" }}>{d.open_rate === null ? "–" : `${Math.round(d.open_rate * 100)}%`}</div>
                <div className="tiny muted">{d.reports_opened} of {d.reports_sent}</div>
              </div>
              <div className="stat">
                <div className="small">Shared with a doctor</div>
                <div className="stat-num">{d.doctor_shares}</div>
                <div className="tiny muted">24-hour links created</div>
              </div>
            </div>

            <div className="row" style={{ alignItems: "stretch", gap: 24 }}>
              <section className="card stack" style={{ flex: "1 1 340px" }}>
                <h2 style={{ fontSize: 18 }}>Messages this month</h2>
                <div className="row small" style={{ justifyContent: "space-between" }}>
                  <span>Used</span>
                  <span><b>{d.messages.used.toLocaleString()}</b> of {d.messages.quota.toLocaleString()} included</span>
                </div>
                <div className="bar"><div style={{ width: `${usedPct}%` }} /></div>
                {Object.keys(d.messages.by_channel).length > 1 && (
                  <div className="row small" style={{ justifyContent: "space-between" }}>
                    <span className="muted">By channel</span>
                    <span>SMS <b>{d.messages.by_channel.sms || 0}</b> · WhatsApp <b>{d.messages.by_channel.whatsapp || 0}</b></span>
                  </div>
                )}
                {Object.entries(d.messages.by_kind).map(([k, n]) => (
                  <div key={k} className="row small" style={{ justifyContent: "space-between" }}>
                    <span className="muted">{KIND_LABEL[k] || k}</span>
                    <b>{n}</b>
                  </div>
                ))}
              </section>
              <section className="card stack" style={{ flex: "2 1 480px" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2 style={{ fontSize: 18 }}>Reminders due in the next 7 days</h2>
                  {me?.role === "admin" && <button className="btn" onClick={runReminders}>Send due reminders now</button>}
                </div>
                {d.upcoming_reminders.length === 0 ? (
                  <p className="muted small">None due this week.</p>
                ) : (
                  <table>
                    <thead><tr><th>Test</th><th>Patients due</th></tr></thead>
                    <tbody>
                      {d.upcoming_reminders.map((u) => (
                        <tr key={u.test_code}><td><b>{u.name}</b></td><td>{u.count}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {msg && <p className="ok small" role="status">{msg}</p>}
              </section>
            </div>
          </>
        )}
      </main>
    </>
  );
}
