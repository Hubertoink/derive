import Link from "next/link";

import { BrandLogo } from "./BrandLogo";

export type SiteSection = "home" | "archive" | "profile" | "curator" | "settings" | null;

const navigation = [
  { key: "home", href: "/", label: "Für dich" },
  { key: "archive", href: "/archiv", label: "Archiv" },
  { key: "profile", href: "/leseprofil", label: "Leseprofil" },
  { key: "curator", href: "/ki", label: "KI-Kurator" },
  { key: "settings", href: "/einstellungen", label: "Einstellungen" },
] as const;

export function SiteHeader({ active, dateLabel }: { active: SiteSection; dateLabel?: string }) {
  return (
    <header className="site-header">
      <BrandLogo />
      <nav aria-label="Hauptnavigation">
        {navigation.map((item) => (
          <Link className={active === item.key ? "is-active" : undefined} href={item.href} key={item.key}>
            {item.label}
          </Link>
        ))}
      </nav>
      {dateLabel ? <time className="date-label" dateTime={new Date().toISOString().slice(0, 10)}>{dateLabel}</time> : null}
    </header>
  );
}
