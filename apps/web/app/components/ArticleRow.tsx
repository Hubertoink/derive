import Link from "next/link";
import { IconRefresh } from "@tabler/icons-react";

import { Article } from "../types";
import { CopyLinkButton } from "./CopyLinkButton";
import { SaveArticleButton } from "./SaveArticleButton";

export function formatDiscoveryDate(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Berlin",
  }).format(date);
}

export function ArticleRow({ article, showReason = false, onRefresh, refreshDisabled = false }: { article: Article; showReason?: boolean; onRefresh?: () => void; refreshDisabled?: boolean }) {
  const curationReason = article.reason ?? article.curation_reason;
  const discoveryDate = article.discovery_method === "ai_web" ? formatDiscoveryDate(article.discovered_at) : null;
  return (
    <article className="article-row" tabIndex={0}>
      <div className="article-actions">
        <SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} />
        <CopyLinkButton url={article.canonical_url} compact hover />
        {onRefresh ? <button className="article-refresh" type="button" onClick={onRefresh} disabled={refreshDisabled} aria-label="Artikel austauschen" title={refreshDisabled ? "Keine weiteren Artikel verfügbar" : "Artikel austauschen"}><IconRefresh size={15} stroke={1.8} aria-hidden="true" /></button> : null}
      </div>
      <div className="article-row__eyebrow">
        <span>{article.source}{discoveryDate ? <small className="article-discovery-date" title="Von der KI hinzugefügt"> ({discoveryDate})</small> : null}</span>
        <span aria-hidden="true">/</span>
        <span>{article.reading_minutes} Min. Lesezeit</span>
        {!article.is_read ? <span className="new-badge">Neu</span> : null}
        {article.discovery_method === "ai_web" ? <span className="ai-badge">KI</span> : null}
      </div>
      <h3>
        <Link href={`/artikel/${article.id}`}>{article.title}</Link>
      </h3>
      <p>{article.dek}</p>
      <div className="article-row__footer">
        <span>{article.author}</span>
        <span>{article.topics.slice(0, 2).join(" · ")}</span>
        {article.access_status === "paywalled" ? <span className="access-badge">Paywall</span> : null}
      </div>
      {showReason && curationReason ? <p className="curator-note">Kuratiert: {curationReason}</p> : null}
    </article>
  );
}

