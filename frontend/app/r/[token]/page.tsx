"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LangToggle } from "@/components/Brand";
import { ListenButton } from "@/components/Listen";
import { api } from "@/lib/api";
import { getLang, Lang, saveLang, T } from "@/lib/i18n";

type LinkInfo = { lab: { id: number; name: string; name_bn: string | null }; masked_phone: string; language: Lang };

export default function ReportLink() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [lang, setLang] = useState<Lang>("bn");
  const [info, setInfo] = useState<LinkInfo | null>(null);
  const [step, setStep] = useState<"start" | "code">("start");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const t = T[lang];

  useEffect(() => {
    setLang(getLang());
    api<LinkInfo>(`/api/public/r/${token}`)
      .then(async (li) => {
        setInfo(li);
        // Already signed in on this phone with the same number? Skip the code (saves an SMS).
        try {
          const me = await api<{ masked_phone: string }>("/api/patient/me");
          if (me.masked_phone === li.masked_phone) router.replace(`/wallet?lab=${li.lab.id}`);
        } catch {
          /* not signed in on this phone yet */
        }
      })
      .catch(() => setError("invalid"));
  }, [token, router]);

  function changeLang(l: Lang) {
    setLang(l);
    saveLang(l);
  }

  async function sendCode() {
    setBusy(true);
    setError("");
    try {
      await api("/api/patient/otp/request", { body: { link_token: token } });
      setStep("code");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/patient/otp/verify", { body: { link_token: token, code } });
      if (getLang() !== lang) saveLang(lang);
      api("/api/patient/me", { method: "PATCH", body: { language: lang } }).catch(() => {});
      router.push(`/wallet?lab=${info?.lab.id ?? ""}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error === "invalid") {
    return <main className="phone-shell"><div className="phone-body"><p className="error">{t.linkInvalid}</p></div></main>;
  }

  const labName = info ? (lang === "bn" && info.lab.name_bn ? info.lab.name_bn : info.lab.name) : "";

  return (
    <main className="phone-shell">
      <header className="phone-head">
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
          <b style={{ fontSize: 17 }}>{labName}</b>
          <span className="tiny muted">{t.viaReportBox}</span>
        </div>
        <LangToggle lang={lang} onChange={changeLang} />
      </header>
      <div className="phone-body" style={{ gap: 22, paddingTop: 32 }}>
        <div className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
            <h1 style={{ fontSize: 26 }}>{t.seeReport}</h1>
            <ListenButton lang={lang} label={t.listen} stopLabel={t.stopListening}
                          text={`${labName}. ${t.seeReport}. ${step === "start" ? `${t.sendCodeTo} ${t.sendCode}` : t.enterCode}.`} />
          </div>
          <p className="muted" style={{ fontSize: 17 }}>
            {step === "start" ? t.sendCodeTo : t.sentCodeTo} <b style={{ color: "var(--ink)" }}>{info?.masked_phone}</b>
          </p>
        </div>

        {step === "start" ? (
          <button className="btn btn-primary btn-big" onClick={sendCode} disabled={busy || !info}>{t.sendCode}</button>
        ) : (
          <form onSubmit={verify} className="stack" style={{ gap: 16 }}>
            <label className="stack" style={{ gap: 8 }}>
              <span className="label" style={{ fontSize: 15 }}>{t.enterCode}</span>
              <input className="input code-input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                     onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />
            </label>
            <button className="btn btn-primary btn-big" disabled={busy || code.length !== 6}>{t.viewReport}</button>
            <button type="button" className="btn btn-big" style={{ fontSize: 17 }} onClick={sendCode} disabled={busy}>{t.resend}</button>
          </form>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <p className="tiny muted" style={{ marginTop: "auto", textAlign: "center" }}>{t.privacy}</p>
      </div>
    </main>
  );
}
