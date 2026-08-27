"use client";

import Link from "next/link";
import { IconBookmark, IconMessageCircle, IconMoon, IconSearch, IconSparkles, IconSun, IconUser, IconX } from "@tabler/icons-react";
import { useEffect, useState } from "react";

export function FloatingMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const syncTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    syncTheme();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("reado-theme-change", syncTheme);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("reado-theme-change", syncTheme);
    };
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("reado-theme", next);
    document.documentElement.dataset.theme = next;
    window.dispatchEvent(new CustomEvent("reado-theme-change", { detail: next }));
  }

  return (
    <nav className={`floating-menu${isOpen ? " is-open" : ""}`} aria-label="Schnellzugriffe">
      <div className="floating-menu__actions" id="floating-menu-actions">
        <Link className="floating-menu__action" href="/suche" onClick={() => setIsOpen(false)} aria-label="Archiv durchsuchen" data-label="Suche">
          <IconSearch aria-hidden="true" strokeWidth={1.7} />
        </Link>
        <Link className="floating-menu__action" href="/ki" onClick={() => setIsOpen(false)} aria-label="KI-Kurator öffnen" data-label="KI-Kurator">
          <IconSparkles aria-hidden="true" strokeWidth={1.7} />
        </Link>
        <Link className="floating-menu__action" href="/merkliste" onClick={() => setIsOpen(false)} aria-label="Merkliste öffnen" data-label="Merkliste">
          <IconBookmark aria-hidden="true" strokeWidth={1.7} />
        </Link>
        <Link className="floating-menu__action" href="/leseprofil" onClick={() => setIsOpen(false)} aria-label="Leseprofil und Rückblick öffnen" data-label="Rückblick">
          <IconMessageCircle aria-hidden="true" strokeWidth={1.7} />
        </Link>
        <Link className="floating-menu__action" href="/konto" onClick={() => setIsOpen(false)} aria-label="Konto öffnen" data-label="Konto">
          <IconUser aria-hidden="true" strokeWidth={1.7} />
        </Link>
        <button className="floating-menu__action" type="button" onClick={toggleTheme} aria-label={theme === "dark" ? "Helles Theme aktivieren" : "Dunkles Theme aktivieren"} data-label={theme === "dark" ? "Hell" : "Dunkel"}>
          {theme === "dark" ? <IconSun aria-hidden="true" strokeWidth={1.7} /> : <IconMoon aria-hidden="true" strokeWidth={1.7} />}
        </button>
      </div>
      <button className="floating-menu__toggle" type="button" aria-expanded={isOpen} aria-controls="floating-menu-actions" onClick={() => setIsOpen((open) => !open)}>
        <span className="sr-only">Schnellzugriffe {isOpen ? "schließen" : "öffnen"}</span>
        <IconX className="floating-menu__close-icon" aria-hidden="true" strokeWidth={1.6} />
        <span className="floating-menu__plus" aria-hidden="true" />
      </button>
    </nav>
  );
}
