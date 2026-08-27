"use client";

import Link from "next/link";
import { IconX } from "@tabler/icons-react";
import { KeyboardEvent, MouseEvent, useMemo, useRef, useState } from "react";

import { Article } from "../types";
import { SaveArticleButton } from "./SaveArticleButton";

function normalizeSearch(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("de-DE")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function searchableText(article: Article) {
  return normalizeSearch([
    article.title,
    article.source,
    article.author,
    article.dek,
    article.curation_reason,
    ...article.topics,
  ].filter(Boolean).join(" "));
}

function levenshteinDistance(left: string, right: string, limit: number) {
  if (Math.abs(left.length - right.length) > limit) return limit + 1;
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    let rowMinimum = current[0];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const cost = left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
      const value = Math.min(
        current[rightIndex - 1] + 1,
        previous[rightIndex] + 1,
        previous[rightIndex - 1] + cost,
      );
      current[rightIndex] = value;
      rowMinimum = Math.min(rowMinimum, value);
    }
    if (rowMinimum > limit) return limit + 1;
    previous = current;
  }
  return previous[right.length];
}

function tokenMatchScore(queryToken: string, textTokens: string[]) {
  const exact = textTokens.some((token) => token.includes(queryToken));
  if (exact) return 0;
  // Very short words are too ambiguous for typo matching ("ai" → "an").
  if (queryToken.length < 3) return null;
  const limit = queryToken.length <= 5 ? 1 : 2;
  let best = limit + 1;
  for (const textToken of textTokens) {
    best = Math.min(best, levenshteinDistance(queryToken, textToken, limit));
  }
  return best <= limit ? best : null;
}

function searchScore(article: Article, queryTokens: string[]) {
  const textTokens = searchableText(article).split(" ").filter(Boolean);
  const scores = queryTokens.map((token) => tokenMatchScore(token, textTokens));
  return scores.some((score) => score === null)
    ? null
    : scores.reduce<number>((total, score) => total + (score ?? 0), 0);
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
  const queryTokens = normalizeSearch(query).split(" ").filter(Boolean);
  const hasQuery = queryTokens.length > 0;
  const results = useMemo(
    () => queryTokens.length
      ? articles
        .map((article, index) => ({ article, index, score: searchScore(article, queryTokens) }))
        .filter((entry): entry is { article: Article; index: number; score: number } => entry.score !== null)
        .sort((left, right) => left.score - right.score || left.index - right.index)
        .map((entry) => entry.article)
      : [],
    [articles, queryTokens.join(" ")],
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
          {!loading && !error && !hasQuery ? <p className="search-overlay__state">Tippe einen Suchbegriff ein. Die passenden Texte erscheinen hier.</p> : null}
          {!loading && !error && hasQuery ? <div className="search-results-heading"><p><strong>{results.length}</strong> {results.length === 1 ? "Text" : "Texte"} für „{query.trim()}“</p></div> : null}
          {!loading && !error && hasQuery && results.length ? (
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
          {!loading && !error && hasQuery && !results.length ? <p className="search-empty">Keine Texte gefunden. Probiere einen kürzeren Begriff oder eine andere Schreibweise.</p> : null}
        </div>
      </section>
    </div>
  );
}
