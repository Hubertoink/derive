"use client";

import Link from "next/link";
import { IconBookmark, IconMessageCircle, IconMoon, IconPlayerStop, IconSearch, IconSparkles, IconSun, IconUser, IconX } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { getArticles } from "../api";
import { Article } from "../types";
import { useBackgroundOperations } from "./BackgroundOperations";
import { SearchOverlay } from "./SearchOverlay";

export function FloatingMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [searchError, setSearchError] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const { operations, cancelOperation } = useBackgroundOperations();
  const operationLabel = operations.length === 1
    ? `${operations[0].label} läuft`
    : `${operations.length} KI-Läufe laufen`;

  useEffect(() => {
    const syncTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    syncTheme();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSearchOpen(false);
        setIsOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("reado-theme-change", syncTheme);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("reado-theme-change", syncTheme);
    };
  }, []);

  useEffect(() => {
    if (!searchOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [searchOpen]);

  async function openSearch() {
    setIsOpen(false);
    setSearchOpen(true);
    if (articles !== null) return;
    setSearchError("");
    try {
      setArticles(await getArticles());
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Das Archiv konnte nicht geladen werden.");
    }
  }

  function closeSearch() {
    setSearchOpen(false);
    window.setTimeout(() => searchButtonRef.current?.focus(), 0);
  }

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("reado-theme", next);
    document.documentElement.dataset.theme = next;
    window.dispatchEvent(new CustomEvent("reado-theme-change", { detail: next }));
  }

  return <>
    <nav className={`floating-menu${isOpen ? " is-open" : ""}${operations.length ? " has-running-operation" : ""}`} aria-label="Schnellzugriffe">
      <div className="floating-menu__actions" id="floating-menu-actions">
        {operations.map((operation) => (
          <button
            className="floating-menu__action floating-menu__action--cancel"
            type="button"
            key={operation.id}
            onClick={() => cancelOperation(operation.id)}
            aria-label={`${operation.label} abbrechen`}
            data-label={`${operation.label} abbrechen`}
          >
            <IconPlayerStop aria-hidden="true" strokeWidth={1.7} />
          </button>
        ))}
        <button ref={searchButtonRef} className="floating-menu__action" type="button" onClick={() => void openSearch()} aria-label="Archiv durchsuchen" data-label="Suche">
          <IconSearch aria-hidden="true" strokeWidth={1.7} />
        </button>
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
      <button className="floating-menu__toggle" type="button" aria-expanded={isOpen} aria-controls="floating-menu-actions" aria-label={operations.length ? `${operationLabel}. Schnellzugriffe ${isOpen ? "schließen" : "öffnen"}` : undefined} onClick={() => setIsOpen((open) => !open)}>
        <span className="sr-only">Schnellzugriffe {isOpen ? "schließen" : "öffnen"}</span>
        {operations.length ? <span className="sr-only" role="status" aria-live="polite">{operationLabel}. Im Menü kannst du den Lauf abbrechen.</span> : null}
        <IconX className="floating-menu__close-icon" aria-hidden="true" strokeWidth={1.6} />
        <span className="floating-menu__plus" aria-hidden="true" />
      </button>
    </nav>
    {searchOpen ? (
      <SearchOverlay
        articles={articles ?? []}
        loading={articles === null && !searchError}
        error={searchError}
        onClose={closeSearch}
      />
    ) : null}
  </>;
}
