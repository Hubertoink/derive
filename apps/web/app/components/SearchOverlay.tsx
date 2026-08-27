"use client";

import Link from "next/link";
import { IconX } from "@tabler/icons-react";
import { KeyboardEvent, MouseEvent, useMemo, useRef, useState } from "react";

import { Article } from "../types";
import { SaveArticleButton } from "./SaveArticleButton";

function searchableText(article: Article) {
  return [
    article.title,
    article.source,
    article.author,
    article.dek,
    article.curation_reason,
    ...article.topics,
  ].filter(Boolean).join(" ").toLocaleLowerCase("de-DE");
}

export function SearchOverlay({
  articles,
  loading,
  error,
  onClose,
}: {
  articles: Article[];
  loading: boolean;
  error: string;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const panelRef = useRef<HTMLElement>(null);
  const normalizedQuery = query.trim().toLocaleLowerCase("de-DE");
  const results = useMemo(
    () => normalizedQuery
      ? articles.filter((article) => searchableText(article).includes(normalizedQuery))
      : [],
    [articles, normalizedQuery],
  );

  function keepOpen(event: MouseEvent<HTMLElement>) {
    event.stopPropagation();
  }

  function keepFocus(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(panelRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled])',
    ) ?? [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="search-overlay" role="presentation" onMouseDown={onClose}>
      <section ref={panelRef} className="search-overlay__panel" role="dialog" aria-modal="true" aria-labelledby="search-overlay-title" onMouseDown={keepOpen} onKeyDown={keepFocus}>
        <button className="search-overlay__close" type="button" onClick={onClose} aria-label="Suche schließen"><IconX aria-hidden="true" /></button>
        <div className="search-overlay__heading">
          <p className="kicker">Im Archiv finden</p>
          <h2 id="search-overlay-title">Wonach suchst du?</h2>
        </div>
        <div className="search-form">
          <label htmlFor="article-search">Suchbegriff</label>
          <div className="search-form__row">
            <input
              id="article-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Titel, Quelle, Autor oder Thema …"
              autoComplete="off"
              autoFocus
            />
            {query ? <button type="button" onClick={() => setQuery("")}>Leeren</button> : null}
          </div>
          <p className="search-form__hint">Durchsucht Titel, Quelle, Autor, Themen und die kurze Einordnung.</p>
        </div>
        <div className="search-overlay__results" aria-live="polite">
          {loading ? <p className="search-overlay__state">Das Archiv wird geladen …</p> : null}
          {error ? <p className="search-overlay__state search-overlay__state--error" role="alert">{error}</p> : null}
          {!loading && !error && !normalizedQuery ? <p className="search-overlay__state">Tippe einen Suchbegriff ein. Die passenden Texte erscheinen hier.</p> : null}
          {!loading && !error && normalizedQuery ? <div className="search-results-heading"><p><strong>{results.length}</strong> {results.length === 1 ? "Text" : "Texte"} für „{query.trim()}“</p></div> : null}
          {!loading && !error && normalizedQuery && results.length ? (
            <div className="search-results-list">
              {results.map((article) => (
                <article className="search-result" key={article.id}>
                  <div className="article-actions"><SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} /></div>
                  <p className="article-row__eyebrow">{article.source} · {article.author} · {article.reading_minutes} Min.{!article.is_read ? <span className="new-badge">Neu</span> : null}</p>
                  <h3><Link href={`/artikel/${article.id}`} onClick={onClose}>{article.title}</Link></h3>
                  {article.dek ? <p>{article.dek}</p> : null}
                  <div className="article-row__footer">{article.topics.slice(0, 3).map((topic) => <span key={topic}>{topic}</span>)}</div>
                </article>
              ))}
            </div>
          ) : null}
          {!loading && !error && normalizedQuery && !results.length ? <p className="search-empty">Keine Texte gefunden. Probiere einen kürzeren Begriff oder eine andere Schreibweise.</p> : null}
        </div>
      </section>
    </div>
  );
}
