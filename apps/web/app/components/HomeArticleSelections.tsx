"use client";

import Link from "next/link";
import { IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import { Article } from "../types";
import { ArticleRow, formatDiscoveryDate } from "./ArticleRow";
import { CopyLinkButton } from "./CopyLinkButton";
import { SaveArticleButton } from "./SaveArticleButton";

type Props = {
  weeklyArticles: Article[];
  recommendationArticles: Article[];
  articlePool: Article[];
  topics: { name: string; article_count: number }[];
};

export function HomeArticleSelections({ weeklyArticles: initialWeekly, recommendationArticles: initialRecommendations, articlePool, topics }: Props) {
  const [weeklyArticles, setWeeklyArticles] = useState(initialWeekly);
  const [recommendationArticles, setRecommendationArticles] = useState(initialRecommendations);

  function replacementFor(current: Article) {
    const visibleIds = new Set([...weeklyArticles, ...recommendationArticles].map((article) => article.id));
    return articlePool.find((article) => article.id !== current.id && !visibleIds.has(article.id)) ?? null;
  }

  function swap(kind: "weekly" | "recommendation", index: number) {
    const current = kind === "weekly" ? weeklyArticles[index] : recommendationArticles[index];
    if (!current) return;
    const replacement = replacementFor(current);
    if (!replacement) return;
    if (kind === "weekly") {
      setWeeklyArticles((articles) => articles.map((article, itemIndex) => itemIndex === index ? replacement : article));
    } else {
      setRecommendationArticles((articles) => articles.map((article, itemIndex) => itemIndex === index ? replacement : article));
    }
  }

  return (
    <>
      <section className="weekly-section" id="auswahl" aria-labelledby="weekly-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Deine Woche in Texten</p><h2 id="weekly-title">Die Auswahl</h2></div>
          <p>Wenig, aber gut. Drei Texte, die sich Zeit nehmen dürfen.</p>
        </div>
        <div className="weekly-grid">
          {weeklyArticles.map((article, index) => {
            const date = article.discovery_method === "ai_web" ? formatDiscoveryDate(article.discovered_at) : null;
            const canSwap = Boolean(replacementFor(article));
            return (
              <article className="weekly-card" key={article.id} tabIndex={0}>
                <div className="article-actions">
                  <SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} />
                  <CopyLinkButton url={article.canonical_url} compact hover />
                  <button className="article-refresh" type="button" onClick={() => swap("weekly", index)} disabled={!canSwap} aria-label="Artikel austauschen" title={canSwap ? "Artikel austauschen" : "Keine weiteren Artikel verfügbar"}><IconRefresh size={15} stroke={1.8} aria-hidden="true" /></button>
                </div>
                <span className="weekly-card__number">0{index + 1}</span>
                <p className="article-row__eyebrow">{article.source}{date ? <small className="article-discovery-date"> ({date})</small> : null} / {article.reading_minutes} Min. {!article.is_read ? <span className="new-badge">Neu</span> : null} {article.discovery_method === "ai_web" ? <span className="ai-badge">KI</span> : null} {article.access_status === "paywalled" ? "· Paywall" : ""}</p>
                <h3><Link href={`/artikel/${article.id}`}>{article.title}</Link></h3>
                {article.dek ? <p>{article.dek}</p> : null}
                <div className="weekly-card__footer"><span>{article.author}</span><Link href={`/artikel/${article.id}`} aria-label={`${article.title} lesen`}>Lesen →</Link></div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="recommendations-section" id="empfehlungen" aria-labelledby="recommendations-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Weiterdenken</p><h2 id="recommendations-title">Weitere Suggestions</h2></div>
          <div className="topic-strip" aria-label="Themenräume">{topics.slice(0, 4).map((topic) => <span key={topic.name}>{topic.name}</span>)}</div>
        </div>
        <div className="recommendations-grid">
          {recommendationArticles.map((article, index) => (
            <ArticleRow key={article.id} article={article} onRefresh={() => swap("recommendation", index)} refreshDisabled={!replacementFor(article)} />
          ))}
        </div>
      </section>
    </>
  );
}
