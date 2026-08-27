"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

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

export function SearchBrowser({ articles }: { articles: Article[] }) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase("de-DE");
  const results = useMemo(
    () => normalizedQuery
      ? articles.filter((article) => searchableText(article).includes(normalizedQuery))
      : articles,
    [articles, normalizedQuery],
  );

  return (
    <section className="search-browser" aria-labelledby="search-results-title">
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
      <div className="search-results-heading">
        <div>
          <p className="kicker">{normalizedQuery ? "Treffer" : "Dein Archiv"}</p>
          <h2 id="search-results-title">{results.length} {results.length === 1 ? "Text" : "Texte"}</h2>
        </div>
        {normalizedQuery ? <p>für „{query.trim()}“</p> : <p>Beginne mit einem Titel, einer Quelle oder einem Autor.</p>}
      </div>
      {results.length ? (
        <div className="search-results-list">
          {results.map((article) => (
            <article className="search-result" key={article.id}>
              <div className="article-actions">
                <SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} />
              </div>
              <p className="article-row__eyebrow">{article.source} · {article.author} · {article.reading_minutes} Min. Lesezeit{!article.is_read ? <span className="new-badge">Neu</span> : null}</p>
              <h3><Link href={`/artikel/${article.id}`}>{article.title}</Link></h3>
              {article.dek ? <p>{article.dek}</p> : null}
              <div className="article-row__footer">{article.topics.slice(0, 3).map((topic) => <span key={topic}>{topic}</span>)}</div>
            </article>
          ))}
        </div>
      ) : <p className="search-empty">Keine Texte für diese Suche. Probiere einen kürzeren Begriff oder eine andere Schreibweise.</p>}
    </section>
  );
}
