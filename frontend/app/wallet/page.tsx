"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { LangToggle } from "@/components/Brand";
import { ListenButton } from "@/components/Listen";
import { QrCode } from "@/components/QrCode";
import { api, ApiError, openPdf } from "@/lib/api";
import { getLang, Lang, saveLang, T } from "@/lib/i18n";

type Person = { key: string; name: string };
type Card = { id: number; title: string; lab: { name: string }; date: string; is_new: boolean; person_key: string; sensitive: boolean };
type Wallet = { wallet_consent: boolean; other_labs_hidden: number; reports: Card[]; reminders: { test: string; due_date: string; person_key: string; lab: string }[] };
type ShareRow = { id: number; report_ids: number[]; active: boolean; views: number; expires_at: string };

function fmtDate(iso: string, lang: Lang) {
  return new Date(iso + "T00:00:00").toLocaleDateString(lang === "bn" ? "bn-BD" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
}

function WalletInner() {
  const router = useRouter();
  const params = useSearchParams();
  const labId = params.get("lab");
  const [lang, setLang] = useState<Lang>("bn");
  const [people, setPeople] = useState<Person[]>([]);
  const [personKey, setPersonKey] = useState<string>("");
  const [w, setW] = useState<Wallet | null>(null);
  const [shares, setShares] = useState<ShareRow[]>([]);
  const [sharing, setSharing] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const [link, setLink] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const t = T[lang];

  const load = useCallback(async () => {
    try {
      const me = await api<{ people: Person[]; language: Lang }>("/api/patient/me");
      setPeople(me.people);
      setPersonKey((k) => k || me.people[0]?.key || "");
      setW(await api<Wallet>(`/api/patient/reports${labId ? `?lab_id=${labId}` : ""}`));
      setShares(await api<ShareRow[]>("/api/patient/shares"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/");
      else setError((e as Error).message);
    }
  }, [labId, router]);

  useEffect(() => {
    setLang(getLang());
    load();
  }, [load]);

  async function signOut() {
    await api("/api/patient/logout", { method: "POST" }).catch(() => {});
    router.replace("/");
  }

  function changeLang(l: Lang) {
    setLang(l);
    saveLang(l);
    api("/api/patient/me", { method: "PATCH", body: { language: l } }).then(load).catch(() => {});
  }

  async function allowWallet() {
    await api("/api/patient/consents/wallet", { body: { give: true } });
    router.replace("/wallet");
    load();
  }

  async function createLink() {
    setError("");
    try {
      const s = await api<{ url: string }>("/api/patient/shares", { body: { report_ids: picked } });
      setLink(s.url);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function stopShare(id: number) {
    await api(`/api/patient/shares/${id}`, { method: "DELETE" });
    load();
  }

  const reports = (w?.reports || []).filter((r) => !personKey || r.person_key === personKey);
  const reminders = (w?.reminders || []).filter((r) => !personKey || r.person_key === personKey);

  // What the Listen button reads: the page title, each report, then how to share.
  const spoken = [
    sharing ? t.pickReports : t.myReports,
    ...reports.map((r) => `${r.sensitive ? (lang === "bn" ? "গোপন রিপোর্ট" : "Private report") : r.title}, ${r.lab.name}, ${fmtDate(r.date, lang)}.`),
    ...reminders.slice(0, 2).map((r) => `${t.nextTest}: ${r.test}, ${fmtDate(r.due_date, lang)}.`),
    sharing && link ? `${t.linkReady}. ${t.expiry}` : "",
  ].filter(Boolean).join(" ");

  return (
    <main className="phone-shell">
      <header className="phone-head" style={{ flexDirection: "column", alignItems: "stretch", gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <b style={{ fontSize: 20 }}>{sharing ? t.showDoctor : t.myReports}</b>
          <LangToggle lang={lang} onChange={changeLang} />
        </div>
        {people.length > 1 && !sharing && (
          <div className="row" role="tablist">
            {people.map((p) => (
              <button key={p.key} role="tab" aria-selected={p.key === personKey} className={`chip ${p.key === personKey ? "on" : ""}`} onClick={() => setPersonKey(p.key)}>
                {p.name}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="phone-body">
        {error && <p className="error" role="alert">{error}</p>}
        {w && reports.length > 0 && (
          <div style={{ alignSelf: "flex-start" }}>
            <ListenButton text={spoken} lang={lang} label={t.listen} stopLabel={t.stopListening} />
          </div>
        )}

        {!sharing && w && w.other_labs_hidden > 0 && (
          <div className="ok stack" style={{ gap: 8 }}>
            <b>{t.walletAsk}</b>
            <span className="small muted">{t.walletAskSub}</span>
            <button className="btn btn-primary" onClick={allowWallet}>{t.walletYes}</button>
          </div>
        )}

        {!sharing && reminders.slice(0, 2).map((r) => (
          <div key={r.test + r.due_date} className="note row" style={{ flexWrap: "nowrap", gap: 12 }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 01-3.4 0" /></svg>
            <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.35 }}>
              <b style={{ fontSize: 15 }}>{t.nextTest}: {r.test}</b>
              <span className="small muted">{fmtDate(r.due_date, lang)} · {r.lab}</span>
            </div>
          </div>
        ))}

        {sharing && <span className="label">{t.pickReports}</span>}
        {w && reports.length === 0 && <p className="muted">{t.noReports}</p>}
        {reports.map((r) => {
          const on = picked.includes(r.id);
          return (
            <button key={r.id} className={`report-card ${sharing && on ? "on" : ""}`}
                    aria-pressed={sharing ? on : undefined}
                    onClick={() => (sharing ? setPicked(on ? picked.filter((x) => x !== r.id) : [...picked, r.id]) : openPdf(`/api/patient/reports/${r.id}/pdf`).then(load).catch((e) => setError(e.message)))}>
              <span className="report-icon" aria-hidden="true">
                {sharing ? (
                  <input type="checkbox" readOnly checked={on} tabIndex={-1} style={{ width: 22, height: 22, accentColor: "var(--primary)" }} />
                ) : (
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2.7S5 10 5 15a7 7 0 0014 0c0-5-7-12.3-7-12.3z" /></svg>
                )}
              </span>
              <span style={{ display: "flex", flexDirection: "column", flexGrow: 1, minWidth: 0, lineHeight: 1.35 }}>
                <b style={{ fontSize: 17 }}>{r.sensitive ? (lang === "bn" ? "গোপন রিপোর্ট" : "Private report") : r.title}</b>
                <span className="small muted">{r.lab.name}</span>
                <span className="tiny muted">{fmtDate(r.date, lang)}</span>
              </span>
              {!sharing && r.is_new && <span className="pill" style={{ background: "var(--primary)", color: "#fff" }}>{t.newTag}</span>}
            </button>
          );
        })}

        {sharing && link && (
          <div className="ok stack" style={{ gap: 10 }}>
            <b>{t.linkReady}</b>
            <span className="small">{t.expiry}</span>
            <div className="row" style={{ flexWrap: "nowrap", gap: 14, alignItems: "center" }}>
              <QrCode value={link} size={150} label="QR" />
              <span className="small">{t.scanQr}</span>
            </div>
            <a className="btn btn-primary" href={`https://wa.me/?text=${encodeURIComponent(link)}`} target="_blank" rel="noopener noreferrer">{t.sendWhatsApp}</a>
            <button className="btn" onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>{copied ? t.copied : t.copyLink}</button>
          </div>
        )}

        {!sharing && shares.length > 0 && (
          <details className="card" style={{ padding: 14 }}>
            <summary className="label">{t.pastShares}</summary>
            {shares.slice(0, 5).map((s) => (
              <div key={s.id} className="list-row small">
                <span style={{ flexGrow: 1 }}>{s.report_ids.length} · {s.views} {t.views}</span>
                {s.active ? <button className="btn-link" onClick={() => stopShare(s.id)}>{t.stop}</button> : <span className="muted">{t.expired}</span>}
              </div>
            ))}
          </details>
        )}
        {!sharing && (
          <div className="row" style={{ justifyContent: "center", gap: 4 }}>
            <Link href="/wallet/settings" className="btn-link small">{t.settings}</Link>
            <button className="btn-link small" onClick={signOut}>{t.signOut}</button>
          </div>
        )}
      </div>

      <div style={{ padding: "0 16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
        {!sharing ? (
          <button className="btn btn-primary btn-big" disabled={reports.length === 0} onClick={() => { setSharing(true); setPicked([]); setLink(""); setCopied(false); }}>{t.showDoctor}</button>
        ) : (
          <>
            {!link && <button className="btn btn-primary btn-big" disabled={picked.length === 0} onClick={createLink}>{t.createLink}</button>}
            <button className="btn btn-big" onClick={() => setSharing(false)}>{t.cancel}</button>
          </>
        )}
      </div>
    </main>
  );
}

export default function WalletPage() {
  return (
    <Suspense fallback={null}>
      <WalletInner />
    </Suspense>
  );
}
