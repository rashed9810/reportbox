import Link from "next/link";
import { BrandMark } from "@/components/Brand";

export default function Home() {
  return (
    <main className="phone-shell" style={{ justifyContent: "center", padding: 24, gap: 20 }}>
      <div className="row" style={{ gap: 12 }}>
        <BrandMark size={44} />
        <h1 style={{ fontSize: 30 }}>ReportBox</h1>
      </div>
      <p className="muted" style={{ fontSize: 18 }}>
        Lab reports on the patient&apos;s phone by SMS. No app download. Repeat-test reminders that bring patients back to your lab.
      </p>
      <Link href="/staff/login" className="btn btn-primary btn-big">Lab staff sign in</Link>
      <p className="tiny muted">Patients: open the link in your SMS to see your report.</p>
    </main>
  );
}
