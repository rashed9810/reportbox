import Link from "next/link";

export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <span className="brand-mark" style={{ width: size, height: size }}>
      <svg width={size * 0.58} height={size * 0.58} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <path d="M8 8h8M8 12h8M8 16h5" />
      </svg>
    </span>
  );
}

export function StaffTopbar({ labName, active, onSignOut, isAdmin }: { labName?: string; active: "send" | "dashboard" | "account" | "settings" | "billing"; onSignOut: () => void; isAdmin?: boolean }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/staff" className="brand">
          <BrandMark />
          <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
            ReportBox
            <span className="tiny muted" style={{ fontWeight: 400 }}>{labName || " "}</span>
          </span>
        </Link>
        <nav className="nav" aria-label="Main">
          <Link href="/staff" className={active === "send" ? "on" : ""}>Send reports</Link>
          <Link href="/staff/dashboard" className={active === "dashboard" ? "on" : ""}>Owner dashboard</Link>
          {isAdmin && <Link href="/staff/settings" className={active === "settings" ? "on" : ""}>Lab settings</Link>}
          {isAdmin && <Link href="/staff/billing" className={active === "billing" ? "on" : ""}>Billing</Link>}
          <Link href="/staff/account" className={active === "account" ? "on" : ""}>{isAdmin ? "Account & staff" : "Account"}</Link>
        </nav>
        <button className="btn" onClick={onSignOut}>Sign out</button>
      </div>
    </header>
  );
}

export function LangToggle({ lang, onChange }: { lang: "bn" | "en"; onChange: (l: "bn" | "en") => void }) {
  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      <button className={lang === "bn" ? "on" : ""} onClick={() => onChange("bn")} aria-pressed={lang === "bn"}>বাংলা</button>
      <button className={lang === "en" ? "on" : ""} onClick={() => onChange("en")} aria-pressed={lang === "en"}>EN</button>
    </div>
  );
}
