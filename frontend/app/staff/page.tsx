"use client";

import { useCallback, useEffect, useState } from "react";
import { StaffTopbar } from "@/components/Brand";
import { api } from "@/lib/api";
import { useStaff } from "@/lib/useStaff";

type Patient = { id: number; name: string; sex: string; age: number | null; consent: boolean; consent_withdrawn: boolean; phone: string };
type Report = { id: number; title: string; status: string; channel: string | null; patient: { name: string }; created_at: string };
type Test = { code: string; name: string; recall_days: number | null };

const NEW = -1;

export default function Reception() {
  const { me, signOut } = useStaff();
  const [catalog, setCatalog] = useState<Test[]>([]);
  const [today, setToday] = useState<Report[]>([]);

  const [phone, setPhone] = useState("");
  const [patients, setPatients] = useState<Patient[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [newP, setNewP] = useState({ name: "", sex: "F", birth_year: "", guardian_name: "" });
  const [consent, setConsent] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [recall, setRecall] = useState(true);
  const [sensitive, setSensitive] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const loadToday = useCallback(() => {
    api<Report[]>("/api/staff/reports").then(setToday).catch(() => {});
  }, []);

  async function resend(r: Report) {
    setError("");
    setDone("");
    try {
      const res = await api<{ message_status: string; message_error?: string }>(`/api/staff/reports/${r.id}/send`, { method: "POST" });
      if (res.message_status === "sent") setDone(`Sent to ${r.patient.name}.`);
      else setError(`SMS failed again: ${res.message_error || "unknown error"}`);
    } catch (e) {
      setError((e as Error).message);
    }
    loadToday();
  }

  useEffect(() => {
    if (!me) return;
    api<Test[]>("/api/staff/catalog").then(setCatalog).catch(() => {});
    loadToday();
  }, [me, loadToday]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setDone("");
    try {
      const list = await api<Patient[]>(`/api/staff/patients?phone=${encodeURIComponent(phone)}`);
      setPatients(list);
      setSelected(list.length ? list[0].id : NEW);
      setConsent(false);
    } catch (err) {
      setError((err as Error).message);
      setPatients(null);
    }
  }

  const current = patients?.find((p) => p.id === selected);
  const birthYear = newP.birth_year ? Number(newP.birth_year) : null;
  const isMinor = selected === NEW && birthYear !== null && new Date().getFullYear() - birthYear < 18;
  const needsConsent = selected === NEW || (current && !current.consent);
  const recallable = codes.some((c) => catalog.find((t) => t.code === c)?.recall_days);

  const canSend = !!file && selected !== null && (!needsConsent || consent) && (selected !== NEW || newP.name.trim().length > 0) && (!isMinor || newP.guardian_name.trim().length > 0);

  async function send() {
    if (!file || selected === null) return;
    setBusy(true);
    setError("");
    setDone("");
    try {
      let patientId = selected;
      let patientName = current?.name || newP.name;
      if (selected === NEW) {
        const p = await api<Patient>("/api/staff/patients", {
          body: { phone, name: newP.name, sex: newP.sex, birth_year: birthYear, consent_given: consent, guardian_name: newP.guardian_name || null },
        });
        patientId = p.id;
        patientName = p.name;
      } else if (current && !current.consent) {
        await api(`/api/staff/patients/${current.id}/consent`, { method: "POST" });
      }
      const form = new FormData();
      form.append("patient_id", String(patientId));
      form.append("test_codes", codes.join(","));
      form.append("recall", String(recall && recallable));
      form.append("sensitive", String(sensitive));
      form.append("file", file);
      const report = await api<{ id: number }>("/api/staff/reports", { form });
      const sent = await api<{ message_status: string; message_error?: string }>(`/api/staff/reports/${report.id}/send`, { method: "POST" });
      if (sent.message_status === "sent") setDone(`Sent to ${patientName}.`);
      else setError(`Report saved, but the SMS failed (${sent.message_error || "unknown error"}). Press Resend in today's list.`);
      setFile(null);
      setCodes([]);
      setSensitive(false);
      setPatients(null);
      setPhone("");
      setNewP({ name: "", sex: "F", birth_year: "", guardian_name: "" });
      loadToday();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <StaffTopbar labName={me?.lab.name} active="send" onSignOut={signOut} isAdmin={me?.role === "admin"} />
      <main className="lab-main">
        <section className="card stack col-main" style={{ gap: 22 }} aria-labelledby="send-title">
          <div className="stack" style={{ gap: 4 }}>
            <h1 id="send-title" style={{ fontSize: 24 }}>Send a report</h1>
            <p className="muted">Search the patient by phone, attach the signed PDF, press Send.</p>
          </div>

          <form onSubmit={search} className="stack" style={{ gap: 8 }}>
            <label className="label" htmlFor="phone">1 · Patient phone number</label>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input id="phone" className="input" inputMode="tel" placeholder="01XXXXXXXXX" value={phone} onChange={(e) => setPhone(e.target.value)} required />
              <button className="btn">Search</button>
            </div>
          </form>

          {patients && (
            <div className="stack" style={{ gap: 10 }}>
              <div role="radiogroup" aria-label="Choose patient" className="row">
                {patients.map((p) => (
                  <label key={p.id} className={`choice ${selected === p.id ? "on" : ""}`}>
                    <input type="radio" name="pt" checked={selected === p.id} onChange={() => { setSelected(p.id); setConsent(false); }} style={{ accentColor: "var(--primary)" }} />
                    <span><b>{p.name}</b> · {p.sex}{p.age !== null ? ` · ${p.age}` : ""}</span>
                  </label>
                ))}
                <label className={`choice ${selected === NEW ? "on" : ""}`}>
                  <input type="radio" name="pt" checked={selected === NEW} onChange={() => { setSelected(NEW); setConsent(false); }} style={{ accentColor: "var(--primary)" }} />
                  <span>+ New family member</span>
                </label>
              </div>
              {patients.length === 0 && <p className="tiny muted">No patients with this number at your lab yet. Add them below.</p>}

              {selected === NEW && (
                <div className="row" style={{ alignItems: "flex-end" }}>
                  <label className="stack" style={{ gap: 4, flex: "2 1 220px" }}>
                    <span className="label">Name</span>
                    <input className="input" value={newP.name} onChange={(e) => setNewP({ ...newP, name: e.target.value })} />
                  </label>
                  <label className="stack" style={{ gap: 4, flex: "1 1 110px" }}>
                    <span className="label">Sex</span>
                    <select className="input" value={newP.sex} onChange={(e) => setNewP({ ...newP, sex: e.target.value })}>
                      <option value="F">Female</option>
                      <option value="M">Male</option>
                      <option value="O">Other</option>
                    </select>
                  </label>
                  <label className="stack" style={{ gap: 4, flex: "1 1 120px" }}>
                    <span className="label">Birth year</span>
                    <input className="input" inputMode="numeric" placeholder="1968" value={newP.birth_year} onChange={(e) => setNewP({ ...newP, birth_year: e.target.value.replace(/\D/g, "").slice(0, 4) })} />
                  </label>
                  {isMinor && (
                    <label className="stack" style={{ gap: 4, flex: "2 1 220px" }}>
                      <span className="label">Parent or guardian giving consent</span>
                      <input className="input" value={newP.guardian_name} onChange={(e) => setNewP({ ...newP, guardian_name: e.target.value })} />
                    </label>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="stack" style={{ gap: 8 }}>
            <span className="label">2 · Attach report (PDF)</span>
            <input type="file" accept="application/pdf" aria-label="Report PDF" onChange={(e) => setFile(e.target.files?.[0] || null)} className="input" style={{ paddingTop: 11 }} />
            <span className="label" style={{ marginTop: 6 }}>Tests in this report</span>
            <div className="row">
              {catalog.map((t) => {
                const on = codes.includes(t.code);
                return (
                  <button key={t.code} type="button" aria-pressed={on} className={`chip ${on ? "on" : ""}`} onClick={() => setCodes(on ? codes.filter((c) => c !== t.code) : [...codes, t.code])}>
                    {t.name}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="stack" style={{ gap: 10 }}>
            <span className="label">3 · Consent and reminder</span>
            {current?.consent_withdrawn && (
              <p className="note small" role="status">
                <b>{current.name} turned off digital reports from your lab</b> in their ReportBox settings. Only tick
                the box below if they ask, here at the counter, to receive them again.
              </p>
            )}
            {needsConsent && (
              <label className="check">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  <b>Patient agreed to get reports by SMS.</b>{" "}
                  <span className="muted">Ask: &ldquo;আপনার রিপোর্ট কি SMS-এ লিংক হিসেবে পাঠাতে পারি?&rdquo;</span>
                </span>
              </label>
            )}
            {!needsConsent && current && <p className="tiny muted">Consent already recorded for {current.name}.</p>}
            <label className="check" style={{ background: "var(--amber-tint)", opacity: recallable ? 1 : 0.6 }}>
              <input type="checkbox" checked={recall && recallable} disabled={!recallable} onChange={(e) => setRecall(e.target.checked)} style={{ accentColor: "var(--amber)" }} />
              <span><b>Remind for the repeat test</b> <span className="muted">{recallable ? "(SMS from your lab when it is due)" : "(pick a test like HbA1c, Lipid or TSH)"}</span></span>
            </label>
            <label className="check">
              <input type="checkbox" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} />
              <span><b>Sensitive report</b> <span className="muted">(marks it private in the patient&apos;s list)</span></span>
            </label>
          </div>

          {error && <p className="error" role="alert">{error}</p>}
          {done && <p className="ok" role="status">{done}</p>}
          <div className="row" style={{ gap: 16 }}>
            <button className="btn btn-primary" style={{ minHeight: 56, fontSize: 18, padding: "0 28px" }} disabled={!canSend || busy} onClick={send}>
              {busy ? "Sending…" : "Send to patient"}
            </button>
            {me?.lab.sms_sender_id && <span className="small muted">Goes by SMS as &ldquo;{me.lab.sms_sender_id}&rdquo;, or WhatsApp if the patient chose it</span>}
          </div>
        </section>

        <aside className="card stack col-side" aria-labelledby="today-title">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 id="today-title" style={{ fontSize: 18 }}>Today&apos;s reports</h2>
            <button className="btn-link small" onClick={loadToday}>Refresh</button>
          </div>
          {today.length === 0 && <p className="muted small">Nothing sent yet today.</p>}
          <div>
            {today.map((r) => (
              <div key={r.id} className="list-row">
                <span className="tiny muted" style={{ width: 46 }}>{new Date(r.created_at + "Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                <div style={{ flexGrow: 1, display: "flex", flexDirection: "column" }}>
                  <b>{r.patient.name}</b>
                  <span className="tiny muted">{r.title}</span>
                </div>
                {r.status === "sms_failed" || r.status === "draft" ? (
                  <button className="btn" style={{ minHeight: 36, padding: "0 12px", fontSize: 14, color: "var(--danger)", borderColor: "var(--danger)" }} onClick={() => resend(r)}>
                    {r.status === "draft" ? "Send" : "Message failed · Resend"}
                  </button>
                ) : (
                  <span className={`pill pill-${r.status}`}>
                    {r.status === "opened" ? "Opened" : "Sent"}{r.channel === "whatsapp" ? " · WhatsApp" : ""}
                  </span>
                )}
              </div>
            ))}
          </div>
        </aside>
      </main>
    </>
  );
}
