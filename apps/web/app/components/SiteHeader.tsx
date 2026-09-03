import Link from "next/link";

import { BrandLogo } from "./BrandLogo";
import { FloatingMenu } from "./FloatingMenu";

export type SiteSection = "home" | "archive" | "profile" | "questions" | "curator" | "settings" | null;

type NavigationKey = Exclude<SiteSection, null>;
type NavigationChild = { key: NavigationKey; href: string; label: string };
type NavigationItem = { key: NavigationKey; href: string; label: string; children?: readonly NavigationChild[] };

const navigation: readonly NavigationItem[] = [
  { key: "home", href: "/", label: "Für dich", children: [{ key: "archive", href: "/archiv", label: "Archiv" }] },
  { key: "profile", href: "/leseprofil", label: "Leseprofil", children: [{ key: "questions", href: "/fragen", label: "Offene Fragen" }] },
  { key: "curator", href: "/ki", label: "KI-Kurator" },
  { key: "settings", href: "/einstellungen", label: "Einstellungen" },
] as const;

export function SiteHeader({ active, dateLabel }: { active: SiteSection; dateLabel?: string }) {
  return (
    <>
      <header className="site-header">
        <BrandLogo />
        <nav aria-label="Hauptnavigation">
          <ul className="site-header__nav">
            {navigation.map((item) => {
              const isActive = active === item.key || item.children?.some((child) => child.key === active);

              return (
                <li className="site-header__item" key={item.key}>
                  <Link className={isActive ? "is-active" : undefined} href={item.href}>
                    {item.label}
                  </Link>
                  {item.children ? (
                    <ul className="site-header__subnav">
                      {item.children.map((child) => (
                        <li key={child.key}>
                          <Link className={active === child.key ? "is-active" : undefined} href={child.href}>
                            {child.label}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </nav>
        {dateLabel ? <time className="date-label" dateTime={new Date().toISOString().slice(0, 10)}>{dateLabel}</time> : null}
      </header>
      <FloatingMenu />
    </>
  );
}
