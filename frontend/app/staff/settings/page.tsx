"use client";

import { useEffect, useState } from "react";
import { StaffTopbar } from "@/components/Brand";
import { api } from "@/lib/api";
import { useStaff } from "@/lib/useStaff";

type Rule = { test_code: string; name: string; name_bn: string; default_days: number | null; enabled: boolean; days: number | null };
type LabInfo = { id: number; name: string; name_bn: string | null; address: string | null; dghs_licence: string | null; sms_sender_id: string | null; plan_name: string; recall_rules: Rule[] };

export default function LabSettings() {
  const { me, signOut } = useStaff();
  const [lab, setLab] = useState<LabInfo | null>(null);
  const [form, setForm] = useState({ name: "", name_bn: "", address: "" });
  const [rules, setRules] = useState<Rule[]>([]);
  const [labMsg, setLabMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [ruleMsg, setRuleMsg] = useState<{ ok: boolean; text: string } | null>(null);

  function apply(l: LabInfo) {
    setLab(l);
    setForm({ name: l.name, name_bn: l.name_bn || "", address: l.address || "" });
    setRules(l.recall_rules);
  }

  useEffect(() => {
    if (me?.role === "admin") api<LabInfo>("/api/staff/lab").then(apply).catch((e) => setLabMsg({ ok: false, text: e.message }));
  }, [me]);

  async function saveLab(e: React.FormEvent) {
    e.preventDefault();
    try {
      apply(await api<LabInfo>("/api/staff/lab", { method: "PATCH", body: form }));
      setLabMsg({ ok: true, text: "Saved." });
    } catch (err) {
      setLabMsg({ ok: false, text: (err as Error).message });
    }
  }

  async function saveRules() {
    try {
      const saved = await api<Rule[]>("/api/staff/lab/recall-rules", {
        method: "PUT",
        body: rules.map((r) => ({ test_code: r.test_code, enabled: r.enabled, days: r.enabled ? r.days : null })),
      });
      setRules(saved);
      setRuleMsg({ ok: true, text: "Saved. New reports use these settings; reminders already planned stay as they are." });
    } catch (err) {
      setRuleMsg({ ok: false, text: (err as Error).message });
    }
  }

  function setRule(code: string, change: Partial<Rule>) {
    setRuleMsg(null);
    setRules(rules.map((r) => (r.test_code === code ? { ...r, ...change } : r)));
  }

  if (me && me.role !== "admin") {
    return (
      <>
        <StaffTopbar labName={me.lab.name} active="settings" onSignOut={signOut} />
        <main className="lab-main"><p className="muted">Only the lab admin can change lab settings.</p></main>
      </>
    );
  }

  return (
    <>
      <StaffTopbar labName={me?.lab.name} active="settings" onSignOut={signOut} isAdmin />
      <main className="lab-main">
        <section className="card stack col-side" aria-labelledby="lab-title">
          <h1 id="lab-title" style={{ fontSize: 20 }}>Lab details</h1>
          <p className="small muted">These names appear in every SMS and on the patient&apos;s phone.</p>
          {!lab && <p className="muted small">Loading…</p>}
          {lab && (
          <form className="stack" onSubmit={saveLab}>
            <label className="stack" style={{ gap: 4 }}>
              <span className="label">Lab name (English)</span>
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required minLength={2} />
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <span className="label">Lab name (Bangla)</span>
              <input className="input" value={form.name_bn} onChange={(e) => setForm({ ...form, name_bn: e.target.value })} />
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <span className="label">Address</span>
              <input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </label>
            {labMsg && <p className={labMsg.ok ? "ok small" : "error small"} role="status">{labMsg.text}</p>}
            <button className="btn btn-primary">Save</button>
          </form>
          )}
          {lab && (
            <div className="small muted stack" style={{ gap: 4, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
              <span>SMS sender name: <b style={{ color: "var(--ink)" }}>{lab.sms_sender_id || "not registered yet"}</b></span>
              <span>DGHS licence: <b style={{ color: "var(--ink)" }}>{lab.dghs_licence || "not given"}</b></span>
              <span>Plan: <b style={{ color: "var(--ink)" }}>{lab.plan_name}</b></span>
              <span>To change these, contact ReportBox. The sender name needs approval from the SMS company first.</span>
            </div>
          )}
        </section>

        <section className="card stack col-main" aria-labelledby="rules-title">
          <h2 id="rules-title" style={{ fontSize: 20 }}>Repeat-test reminders</h2>
          <p className="small muted">
            Choose which tests get a reminder SMS, and after how many days. Reminders are only sent when reception ticks
            &ldquo;Remind for the repeat test&rdquo;, and only between 10 am and 7 pm. Follow your pathologists&apos; and
            doctors&apos; advice on intervals.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ minWidth: 520 }}>
              <thead><tr><th>Test</th><th>Reminder</th><th>After (days)</th><th>Default</th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.test_code}>
                    <td><b>{r.name}</b><div className="tiny muted">{r.name_bn}</div></td>
                    <td>
                      <label className="switch" title={r.enabled ? "On" : "Off"}>
                        <input type="checkbox" role="switch" aria-label={`Reminder for ${r.name}`} checked={r.enabled}
                               onChange={(e) => setRule(r.test_code, { enabled: e.target.checked, days: r.days ?? r.default_days ?? 90 })} />
                        <span />
                      </label>
                    </td>
                    <td>
                      <input className="days" type="number" min={7} max={730} aria-label={`Days for ${r.name}`} disabled={!r.enabled}
                             value={r.enabled ? r.days ?? "" : ""} onChange={(e) => setRule(r.test_code, { days: e.target.value ? Number(e.target.value) : null })} />
                    </td>
                    <td className="small muted">{r.default_days ? `${r.default_days} days` : "Off"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {ruleMsg && <p className={ruleMsg.ok ? "ok small" : "error small"} role="status">{ruleMsg.text}</p>}
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={saveRules}>Save reminder settings</button>
        </section>
      </main>
    </>
  );
}
