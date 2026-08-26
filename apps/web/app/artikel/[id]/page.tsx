import { getArticle } from "../../server-api";
import { ArticleFeedbackPrompt } from "../../components/ArticleFeedbackPrompt";
import { ArticleReadTracker } from "../../components/ArticleReadTracker";
import { CopyLinkButton } from "../../components/CopyLinkButton";
import { ReaderActions } from "../../components/ReaderActions";
import { SiteHeader } from "../../components/SiteHeader";
import { formatDiscoveryDate } from "../../components/ArticleRow";

export const dynamic = "force-dynamic";

export default async function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const article = await getArticle(id);

  return (
    <main className="reader-shell">
      <SiteHeader active="home" />
      <article className="reader">
        <ArticleReadTracker articleId={article.id} isRead={article.is_read} />
        <p className="kicker">{article.source}{article.discovery_method === "ai_web" && formatDiscoveryDate(article.discovered_at) ? <small className="article-discovery-date"> ({formatDiscoveryDate(article.discovered_at)})</small> : null}</p>
        <h1>{article.title}</h1>
        <p className="reader__dek">{article.dek}</p>
        <div className="reader__meta">
          <span>Von {article.author}</span>
          <span>{article.reading_minutes} Min. Lesezeit</span>
          {article.discovery_method === "ai_web" ? <span className="ai-badge">KI-Kurator</span> : null}
          <a href={article.canonical_url} target="_blank" rel="noreferrer">Original öffnen ↗</a>
        </div>
        <ReaderActions articleId={article.id} initiallySaved={article.is_saved} initiallyRead={article.is_read} />
        <ArticleFeedbackPrompt articleId={article.id} initiallyRead={article.is_read} />
        {article.access_status === "paywalled" ? <div className="reader__paywall"><div><p className="kicker">Paywall-Hinweis</p><p>Dieser lesenswerte Artikel kann ein Abonnement erfordern. dérive öffnet ausschließlich die Originalquelle.</p></div><CopyLinkButton url={article.canonical_url} /></div> : null}
        {article.content_html && article.fulltext_source !== "ai_summary" && article.fulltext_source !== "subscriber_capture" ? <div className="reader__body" dangerouslySetInnerHTML={{ __html: article.content_html }} /> : null}
        {article.discovery_method === "ai_web" ? <p className="reader__original-cta"><a href={article.canonical_url} target="_blank" rel="noreferrer">Reportage im Original lesen ↗</a></p> : null}
      </article>
    </main>
  );
}
