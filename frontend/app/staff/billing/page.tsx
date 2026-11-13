"use client";

import { useCallback, useEffect, useState } from "react";
import { StaffTopbar } from "@/components/Brand";
import { api } from "@/lib/api";
import { bdt, monthName } from "@/lib/money";
import { useStaff } from "@/lib/useStaff";

type Plan = { name: string; price_bdt: number; reports: number; messages: number };
type Calc = {
  period: string; plan_name: string; base_paisa: number; discount_paisa: number; reports_used: number; reports_included: number;
  messages_used: number; messages_included: number; extra_reports: number; extra_messages: number; overage_paisa: number;
  vat_paisa: number; total_paisa: number;
};
type Invoice = {
  id: number; number: string; period: string; plan_name: string; base_paisa: number; discount_paisa: number;
  reports_used: number; reports_included: number; messages_used: number; messages_included: number; overage_paisa: number;
  vat_paisa: number; total_paisa: number; status: "unpaid" | "overdue" | "verifying" | "paid" | "void"; due_date: string;
  payment_method: string | null; payment_ref: string | null; paid_at: string | null; note: string | null;
};
type Billing = {
  plan: string; plans: Record<string, Plan>; discount_percent: number; discount_until: string | null; this_month: Calc;
  vat_percent: number; pay_to: { bkash: string | null; nagad: string | null }; invoices: Invoice[];
};

const STATUS: Record<Invoice["status"], { label: string; cls: string }> = {
  unpaid: { label: "Unpaid", cls: "pill-draft" },
  overdue: { label: "Overdue", cls: "pill-draft" },
  verifying: { label: "Payment being checked", cls: "pill-sent" },
  paid: { label: "Paid", cls: "pill-opened" },
  void: { label: "Cancelled", cls: "pill-sent" },
};

function fmtDay(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function Lines({ c }: { c: Calc | Invoice }) {
  return (
    <table style={{ width: "100%" }}>
      <tbody>
        <tr><td>{c.plan_name} plan</td><td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{bdt(c.base_paisa)}</td></tr>
        {c.discount_paisa > 0 && <tr><td>Founding discount</td><td style={{ textAlign: "right", whiteSpace: "nowrap" }}>-{bdt(c.discount_paisa)}</td></tr>}
        <tr>
          <td className="small muted">Reports {c.reports_used.toLocaleString()} of {c.reports_included.toLocaleString()} · messages {c.messages_used.toLocaleString()} of {c.messages_included.toLocaleString()}</td>
          <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{c.overage_paisa > 0 ? `+${bdt(c.overage_paisa)}` : "No extra"}</td>
        </tr>
        {c.vat_paisa > 0 && <tr><td>VAT</td><td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{bdt(c.vat_paisa)}</td></tr>}
        <tr><td><b>Total</b></td><td style={{ textAlign: "right", whiteSpace: "nowrap" }}><b>{bdt(c.total_paisa)}</b></td></tr>
      </tbody>
    </table>
  );
}

function PayForm({ inv, payTo, onDone }: { inv: Invoice; payTo: Billing["pay_to"]; onDone: () => void }) {
  const [method, setMethod] = useState(payTo.bkash ? "bkash" : payTo.nagad ? "nagad" : "bank");
  const [ref, setRef] = useState("");
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await api(`/api/staff/billing/invoices/${inv.id}/payment`, { body: { method, reference: ref } });
      onDone();
    } catch (er) {
      setErr((er as Error).message);
    }
  }

  return (
    <form className="stack" onSubmit={submit} style={{ background: "var(--bg)", borderRadius: 10, padding: 14 }}>
      <b className="small">How to pay</b>
      <ol className="small" style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 }}>
        {payTo.bkash && <li>bKash: send <b>{bdt(inv.total_paisa)}</b> to <b>{payTo.bkash}</b> (Payment).</li>}
        {payTo.nagad && <li>Nagad: send <b>{bdt(inv.total_paisa)}</b> to <b>{payTo.nagad}</b>.</li>}
        {!payTo.bkash && !payTo.nagad && <li>Contact ReportBox for payment details.</li>}
        <li>Use <b>{inv.number}</b> as the reference, if the app asks for one.</li>
        <li>Type the transaction ID (TrxID) from the confirmation SMS below.</li>
      </ol>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <label className="stack" style={{ gap: 4, flex: "0 1 140px" }}>
          <span className="label">Paid with</span>
          <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="bkash">bKash</option>
            <option value="nagad">Nagad</option>
            <option value="bank">Bank transfer</option>
            <option value="cash">Cash</option>
          </select>
        </label>
        <label className="stack" style={{ gap: 4, flex: "1 1 200px" }}>
          <span className="label">Transaction ID</span>
          <input className="input" value={ref} onChange={(e) => setRef(e.target.value)} minLength={4} maxLength={60} required placeholder="e.g. 9AB3XK2LQ" />
        </label>
        <button className="btn btn-primary">I have paid</button>
      </div>
      {err && <p className="error small" role="alert">{err}</p>}
    </form>
  );
}

export default function BillingPage() {
  const { me, signOut } = useStaff();
  const [b, setB] = useState<Billing | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(() => {
    api<Billing>("/api/staff/billing").then(setB).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (me?.role === "admin") load();
  }, [me, load]);

  if (me && me.role !== "admin") {
    return (
      <>
        <StaffTopbar labName={me.lab.name} active="billing" onSignOut={signOut} />
        <main className="lab-main"><p className="muted">Only the lab admin can see billing.</p></main>
      </>
    );
  }

  const plan = b ? b.plans[b.plan] : null;

  return (
    <>
      <StaffTopbar labName={me?.lab.name} active="billing" onSignOut={signOut} isAdmin />
      <main className="lab-main">
        {error && <p className="error" role="alert">{error}</p>}
        {b && plan && (
          <>
            <section className="card stack col-side" aria-labelledby="plan-title">
              <h1 id="plan-title" style={{ fontSize: 20 }}>{plan.name} plan</h1>
              <p className="small">
                {bdt(plan.price_bdt * 100)} a month · {plan.reports.toLocaleString()} reports · {plan.messages.toLocaleString()} messages included.
                Extra: BDT 1 per report, BDT 0.60 per message.
              </p>
              {b.discount_percent > 0 && b.discount_until && (
                <p className="ok small">Founding discount: {b.discount_percent}% off the plan until {fmtDay(b.discount_until)}.</p>
              )}
              <div style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }} className="stack">
                <b>So far this month ({monthName(b.this_month.period)})</b>
                <Lines c={b.this_month} />
                <span className="tiny muted">An estimate. The bill is made on the 1st of next month{b.vat_percent ? `, VAT ${b.vat_percent}% included` : ""}.</span>
              </div>
              <p className="tiny muted">To change plan, contact ReportBox.</p>
            </section>

            <section className="card stack col-main" aria-labelledby="inv-title">
              <h2 id="inv-title" style={{ fontSize: 20 }}>Invoices</h2>
              {b.invoices.length === 0 && <p className="muted small">No invoices yet. Your first bill comes at the start of next month.</p>}
              {b.invoices.map((inv) => {
                const st = STATUS[inv.status];
                const canPay = inv.status === "unpaid" || inv.status === "overdue";
                return (
                  <div key={inv.id} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: 14, gap: 10 }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div style={{ display: "flex", flexDirection: "column" }}>
                        <b>{monthName(inv.period)}</b>
                        <span className="tiny muted">{inv.number} · due {fmtDay(inv.due_date)}</span>
                      </div>
                      <div className="row">
                        <b>{bdt(inv.total_paisa)}</b>
                        <span className={`pill ${st.cls}`} style={inv.status === "overdue" ? { color: "var(--danger)" } : undefined}>{st.label}</span>
                      </div>
                    </div>
                    {inv.note && inv.status === "unpaid" && <p className="error small">Payment not confirmed: {inv.note}. Please check the transaction ID.</p>}
                    {inv.status === "verifying" && <p className="small muted">We received your transaction ID {inv.payment_ref}. We confirm it within one working day.</p>}
                    {inv.status === "paid" && inv.payment_ref && <p className="small muted">Paid by {inv.payment_method} · {inv.payment_ref}</p>}
                    <button className="btn-link small" style={{ alignSelf: "flex-start", padding: 0 }} onClick={() => setOpenId(openId === inv.id ? null : inv.id)}>
                      {openId === inv.id ? "Hide details" : canPay ? "Details and how to pay" : "Details"}
                    </button>
                    {openId === inv.id && (
                      <>
                        <Lines c={inv} />
                        {canPay && <PayForm inv={inv} payTo={b.pay_to} onDone={() => { setOpenId(null); load(); }} />}
                      </>
                    )}
                  </div>
                );
              })}
            </section>
          </>
        )}
      </main>
    </>
  );
}
