"use client";

import { useEffect, useState } from "react";

import { Article } from "../types";
import { ArticleRow } from "./ArticleRow";

export function SavedArticleGallery({ initial }: { initial: Article[] }) {
  const [articles, setArticles] = useState(initial);

  useEffect(() => {
    if (!articles.some((article) => !article.image_url)) return;
    void fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/articles/saved/visuals`, { method: "POST", credentials: "include" })
      .then(async (response) => response.ok ? response.json() as Promise<Article[]> : [])
      .then((enriched) => {
        if (!enriched.length) return;
        const byId = new Map(enriched.map((article) => [article.id, article]));
        setArticles((current) => current.map((article) => byId.get(article.id) ?? article));
      })
      .catch(() => undefined);
  }, [articles]);

  return (
    <div className="saved-gallery" aria-label="Gemerkt">
      {articles.map((article, index) => (
        <div className={`saved-entry ${index % 2 ? "saved-entry--reverse" : ""}`} key={article.id}>
          <ArticleRow article={article} showReason />
          {article.image_url ? (
            <figure className="saved-entry__visual">
              <img src={article.image_url} alt="" />
              {article.image_source_url && article.image_credit ? (
                <figcaption><a href={article.image_source_url} target="_blank" rel="noreferrer">{article.image_credit} ↗</a></figcaption>
              ) : null}
            </figure>
          ) : null}
        </div>
      ))}
    </div>
  );
}
