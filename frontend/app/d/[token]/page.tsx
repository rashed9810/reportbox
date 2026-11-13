"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandMark } from "@/components/Brand";
import { api, openPdf } from "@/lib/api";

type View = { patient: { name: string; sex: string; age: number | null }; expires_at: string; reports: { id: number; title: string; lab: string; date: string }[] };

const SEX: Record<string, string> = { F: "Female", M: "Male", O: "Other" };

function timeLeft(iso: string) {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "Expired";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `Expires in ${h} h ${m} min`;
}

export default function DoctorView() {
  const { token } = useParams<{ token: string }>();
  const [v, setV] = useState<View | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<View>(`/api/public/share/${token}`).then(setV).catch((e) => setError(e.message));
  }, [token]);

  return (
    <main className="phone-shell" lang="en">
      <header className="phone-head">
        <div className="row" style={{ gap: 10 }}>
          <BrandMark size={30} />
          <b style={{ fontSize: 17 }}>ReportBox</b>
        </div>
        {v && <span className="pill pill-draft">{timeLeft(v.expires_at)}</span>}
      </header>
      <div className="phone-body">
        {error && <p className="error" role="alert">{error}</p>}
        {v && (
          <>
            <div className="card stack" style={{ gap: 2 }}>
              <span className="tiny muted">Shared by the patient</span>
              <b style={{ fontSize: 22 }}>{v.patient.name}</b>
              <span className="muted">{SEX[v.patient.sex] || ""}{v.patient.age !== null ? ` · ${v.patient.age} years` : ""}</span>
            </div>
            <h1 style={{ fontSize: 16 }}>{v.reports.length} report{v.reports.length === 1 ? "" : "s"} shared</h1>
            {v.reports.map((r) => (
              <div key={r.id} className="card row" style={{ padding: 14, flexWrap: "nowrap", gap: 12 }}>
                <span className="pill pill-draft" style={{ borderRadius: 6, padding: "14px 8px" }}>PDF</span>
                <span style={{ display: "flex", flexDirection: "column", flexGrow: 1, lineHeight: 1.35 }}>
                  <b>{r.title}</b>
                  <span className="tiny muted">{r.lab} · {new Date(r.date + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
                </span>
                <button className="btn" onClick={() => openPdf(`/api/public/share/${token}/reports/${r.id}/pdf`).catch((e) => setError(e.message))}>Open</button>
              </div>
            ))}
            <p className="ok small" style={{ marginTop: "auto" }}>View only. No login needed. The patient chose these reports and can see when they were opened.</p>
          </>
        )}
      </div>
    </main>
  );
}
