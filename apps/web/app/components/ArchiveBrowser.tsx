"use client";

import { IconAdjustmentsHorizontal, IconX } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { Article } from "../types";
import { ArticleRow } from "./ArticleRow";

type ArchiveGroup = { key: string; date: string; articles: Article[] };
type DateMode = "discovered" | "published";
type SourceMode = "all" | "ai_web" | "subscriber_import";

const dateFormatter = new Intl.DateTimeFormat("de-DE", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

function dateFor(article: Article, mode: DateMode) {
  return new Date(mode === "discovered" ? article.discovered_at ?? article.published_at : article.published_at);
}

function sourceMatches(article: Article, source: SourceMode) {
  if (source === "all") return true;
  if (source === "ai_web") return article.discovery_method === "ai_web";
  if (source === "subscriber_import") return article.discovery_method === "subscriber_import";
  return false;
}

export function ArchiveBrowser({ articles }: { articles: Article[] }) {
  const [isOpen, setIsOpen] = useState(false);
  const [dateMode, setDateMode] = useState<DateMode>("discovered");
  const [sourceMode, setSourceMode] = useState<SourceMode>("all");
  const groups = useMemo(() => {
    const grouped = new Map<string, ArchiveGroup>();
    const matching = articles
      .filter((article) => sourceMatches(article, sourceMode))
      .sort((left, right) => dateFor(right, dateMode).getTime() - dateFor(left, dateMode).getTime());
    for (const article of matching) {
      const date = dateFor(article, dateMode);
      const key = date.toISOString().slice(0, 10);
      const group = grouped.get(key) ?? { key, date: dateFormatter.format(date), articles: [] };
      group.articles.push(article);
      grouped.set(key, group);
    }
    return [...grouped.values()];
  }, [articles, dateMode, sourceMode]);

  return (
    <section className="archive-list" aria-label="Alle Artikel im Archiv">
      <div className="archive-toolbar">
        <p>{groups.reduce((total, group) => total + group.articles.length, 0)} gefundene Texte · sortiert nach {dateMode === "discovered" ? "Entdeckungsdatum" : "Erscheinungsdatum"}</p>
        <div className="archive-filter">
          <button type="button" className="archive-filter__button" aria-expanded={isOpen} aria-controls="archive-filter-popover" onClick={() => setIsOpen((open) => !open)}>
            <IconAdjustmentsHorizontal aria-hidden="true" strokeWidth={1.7} /> Filter
          </button>
          {isOpen ? (
            <div className="archive-filter__popover" id="archive-filter-popover" role="dialog" aria-label="Archiv filtern">
              <div><strong>Archiv filtern</strong><button type="button" onClick={() => setIsOpen(false)} aria-label="Filter schließen"><IconX aria-hidden="true" size={17} /></button></div>
              <label><span>Datum</span><select value={dateMode} onChange={(event) => setDateMode(event.target.value as DateMode)}><option value="discovered">Wann entdeckt</option><option value="published">Wann erschienen</option></select></label>
              <label><span>Herkunft</span><select value={sourceMode} onChange={(event) => setSourceMode(event.target.value as SourceMode)}><option value="all">Alle Quellen</option><option value="ai_web">KI-Kurator</option><option value="subscriber_import">Persönliche Kopien</option></select></label>
            </div>
          ) : null}
        </div>
      </div>
      {groups.length ? groups.map((group) => (
        <section className="archive-day" key={group.key}>
          <h2>{group.date}</h2>
          <div className="archive-day__articles">
            {group.articles.map((article) => <ArticleRow key={article.id} article={article} showReason />)}
          </div>
        </section>
      )) : <p className="archive-empty">Für diesen Filter gibt es noch keine Texte.</p>}
    </section>
  );
}
