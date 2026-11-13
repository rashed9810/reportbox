"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { LangToggle } from "@/components/Brand";
import { api, ApiError } from "@/lib/api";
import { getLang, Lang, saveLang, T } from "@/lib/i18n";

type Me = { masked_phone: string; language: Lang; whatsapp_available: boolean; whatsapp_opt_in: boolean };
type LabRow = { id: number; name: string; people: string[]; receiving: boolean };

export default function PatientSettings() {
  const router = useRouter();
  const [lang, setLang] = useState<Lang>("bn");
  const [me, setMe] = useState<Me | null>(null);
  const [labs, setLabs] = useState<LabRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const t = T[lang];

  const load = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/patient/me"));
      setLabs(await api<LabRow[]>("/api/patient/labs"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/");
      else setError((e as Error).message);
    }
  }, [router]);

  useEffect(() => {
    setLang(getLang());
    load();
  }, [load]);

  function changeLang(l: Lang) {
    setLang(l);
    saveLang(l);
    api("/api/patient/me", { method: "PATCH", body: { language: l } }).then(load).catch(() => {});
  }

  async function toggleWhatsApp(on: boolean) {
    setError("");
    setMe((m) => (m ? { ...m, whatsapp_opt_in: on } : m)); // flip at once; undo if saving fails
    try {
      await api("/api/patient/me", { method: "PATCH", body: { whatsapp_opt_in: on } });
    } catch (e) {
      setMe((m) => (m ? { ...m, whatsapp_opt_in: !on } : m));
      setError((e as Error).message);
    }
  }

  async function stopLab(lab: LabRow) {
    if (!window.confirm(`${lab.name}: ${t.stopLabConfirm}`)) return;
    setBusy(true);
    try {
      await api(`/api/patient/labs/${lab.id}/stop`, { method: "POST" });
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setError("");
    try {
      const res = await fetch("/api/patient/export", { credentials: "same-origin" });
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "my-reportbox-data.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function closeWallet() {
    if (!window.confirm(t.closeConfirm)) return;
    setBusy(true);
    try {
      await api("/api/patient/close", { method: "POST" });
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="phone-shell">
      <header className="phone-head">
        <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <Link href="/wallet" aria-label={t.back} className="btn" style={{ minHeight: 44, padding: "0 12px" }}>‹</Link>
          <b style={{ fontSize: 19 }}>{t.settings}</b>
        </div>
        <LangToggle lang={lang} onChange={changeLang} />
      </header>

      <div className="phone-body">
        {error && <p className="error" role="alert">{error}</p>}
        {me && <p className="small muted">{me.masked_phone}</p>}

        {me?.whatsapp_available && (
          <section className="card row" style={{ flexWrap: "nowrap", gap: 14, padding: 16 }}>
            <div style={{ flexGrow: 1 }}>
              <h2 style={{ fontSize: 17 }} id="wa-title">{t.whatsappTitle}</h2>
              <p className="small muted">{t.whatsappSub}</p>
            </div>
            <label className="switch">
              <input type="checkbox" role="switch" aria-labelledby="wa-title" checked={me.whatsapp_opt_in}
                     onChange={(e) => toggleWhatsApp(e.target.checked)} />
              <span />
            </label>
          </section>
        )}

        <section className="card stack" style={{ padding: 16, gap: 10 }}>
          <h2 style={{ fontSize: 17 }}>{t.labsTitle}</h2>
          <p className="small muted">{t.labsSub}</p>
          {labs.map((lab) => (
            <div key={lab.id} className="list-row">
              <div style={{ flexGrow: 1, display: "flex", flexDirection: "column" }}>
                <b>{lab.name}</b>
                <span className="tiny muted">{lab.people.join(", ")}</span>
              </div>
              {lab.receiving ? (
                <button className="btn danger-btn" style={{ minHeight: 40 }} disabled={busy} onClick={() => stopLab(lab)}>{t.stopLab}</button>
              ) : (
                <span className="pill pill-sent">{t.stopped}</span>
              )}
            </div>
          ))}
        </section>

        <section className="card stack" style={{ padding: 16, gap: 10 }}>
          <h2 style={{ fontSize: 17 }}>{t.downloadTitle}</h2>
          <p className="small muted">{t.downloadSub}</p>
          <button className="btn" onClick={download}>{t.download}</button>
        </section>

        <section className="card stack" style={{ padding: 16, gap: 10 }}>
          <h2 style={{ fontSize: 17 }}>{t.closeTitle}</h2>
          <p className="small muted">{t.closeSub}</p>
          <button className="btn danger-btn" disabled={busy} onClick={closeWallet}>{t.closeBtn}</button>
        </section>
      </div>
    </main>
  );
}
