import Link from "next/link";
import { IconExternalLink } from "@tabler/icons-react";

import { getHome, getSetup } from "./server-api";
import { ArticleRow, formatDiscoveryDate } from "./components/ArticleRow";
import { HomeArticleSelections } from "./components/HomeArticleSelections";
import { CopyLinkButton } from "./components/CopyLinkButton";
import { PodcastRecommendations } from "./components/PodcastRecommendations";
import { SiteHeader } from "./components/SiteHeader";
import { SetupWizard } from "./components/SetupWizard";
import { SaveArticleButton } from "./components/SaveArticleButton";
import { Article } from "./types";

export const dynamic = "force-dynamic";

const todayLabel = new Intl.DateTimeFormat("de-DE", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "Europe/Berlin",
}).format(new Date());

function articleKey(article: Pick<Article, "id" | "canonical_url">) {
  try {
    const url = new URL(article.canonical_url, "http://derive.local");
    for (const key of [...url.searchParams.keys()]) {
      if (key.toLowerCase().startsWith("utm_") || ["fbclid", "gclid", "mc_cid", "mc_eid"].includes(key.toLowerCase())) {
        url.searchParams.delete(key);
      }
    }
    url.searchParams.sort();
    return `${url.origin}${url.pathname.replace(/\/$/, "") || "/"}${url.search}`;
  } catch {
    return `article:${article.id}`;
  }
}

function uniqueArticles(articles: Article[]) {
  const seen = new Set<string>();
  return articles.filter((article) => {
    const key = articleKey(article);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default async function HomePage() {
  const setup = await getSetup();
  if (!setup.setup_completed) return <SetupWizard initial={setup} onboarding />;

  const home = await getHome();
  const lead = home.for_you[0] ?? home.today[0];
  if (!lead) {
    return (
      <main className="page-shell home-shell">
        <SiteHeader active="home" dateLabel={todayLabel} />
        <section className="home-empty" aria-labelledby="empty-home-title">
          <p className="kicker">Dein Leseraum ist bereit</p>
          <h1 id="empty-home-title">Die erste Auswahl darf noch entstehen.</h1>
          <p>
            Starte eine KI-Suche, damit dérive passende Texte für deinen Leseraum
            zusammenstellen kann. Danach erscheint deine Auswahl automatisch hier.
          </p>
          <div className="home-empty__actions">
            <Link className="home-empty__primary" href="/ki">KI-Kurator öffnen <span aria-hidden="true">→</span></Link>
            <Link className="home-empty__secondary" href="/einstellungen">Einstellungen prüfen</Link>
          </div>
        </section>
      </main>
    );
  }

  const weeklyArticles = uniqueArticles([
    ...home.for_you.filter((article) => article.id !== lead.id),
    ...home.discover.filter((article) => article.id !== lead.id),
  ]).slice(0, 3);
  const selectedKeys = new Set([lead, ...weeklyArticles].map(articleKey));
  const recommendationArticles = uniqueArticles(home.discover)
    .filter((article) => !selectedKeys.has(articleKey(article)))
    .slice(0, 3);
  const articlePool = uniqueArticles([...home.for_you, ...home.discover]).filter((article) => article.id !== lead.id);
  const hero = home.hero_visual;
  const leadDiscoveryDate = lead.discovery_method === "ai_web" ? formatDiscoveryDate(lead.discovered_at) : null;

  return (
    <main className="page-shell home-shell">
      <SiteHeader active="home" dateLabel={todayLabel} />

      <section className="home-intro" aria-labelledby="welcome-title">
        <h1 id="welcome-title">Lies, was nachklingt.</h1>
        <p>Eine persönliche Auswahl für langsame Gedanken und gute Umwege.</p>
      </section>

      <section className="hero-section" aria-labelledby="hero-title">
        <article className="hero-article" tabIndex={0}>
          <div className="article-actions"><SaveArticleButton articleId={lead.id} initiallySaved={lead.is_saved} /></div>
          <img className="hero-article__image" src={hero.url ?? "/images/hero-cappadocia.jpg"} alt={hero.alt ?? "Tauben über einer felsigen Landschaft in Kappadokien"} />
          <div className="hero-article__shade" />
          <div className="hero-article__content">
            <p className="hero-article__meta">{lead.source}{leadDiscoveryDate ? <small className="article-discovery-date" title="Von der KI hinzugefügt"> ({leadDiscoveryDate})</small> : null} <span>•</span> {lead.reading_minutes} Min. Lesezeit {!lead.is_read ? <span className="new-badge">Neu</span> : null} {lead.discovery_method === "ai_web" ? <span className="ai-badge">KI</span> : null} {lead.access_status === "paywalled" ? <><span>•</span> Paywall</> : null}</p>
            <h2 id="hero-title"><Link href={`/artikel/${lead.id}`}>{lead.title}</Link></h2>
            {lead.dek ? <p className="hero-article__dek">{lead.dek}</p> : null}
            <div className="hero-article__footer">
              <span>Von {lead.author}</span>
              <Link className="hero-article__cta" href={`/artikel/${lead.id}`}>Artikel lesen <span aria-hidden="true">→</span></Link>
            </div>
          </div>
          <span className="hero-article__tag">Diese Woche</span>
          {hero.source_url && hero.credit ? (
            <a className="hero-article__credit" href={hero.source_url} target="_blank" rel="noreferrer" title={`${hero.credit} auf Pexels`}>
              <span>{hero.credit}</span><IconExternalLink size={14} aria-hidden="true" />
            </a>
          ) : null}
        </article>
      </section>

      <section className="weekly-section legacy-home-section" id="auswahl" aria-labelledby="weekly-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Deine Woche in Texten</p><h2 id="weekly-title">Die Auswahl</h2></div>
          <p>Wenig, aber gut. Drei Texte, die sich Zeit nehmen dürfen.</p>
        </div>
        <div className="weekly-grid">
          {weeklyArticles.map((article, index) => (
            <article className="weekly-card" key={article.id}>
              <SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} />
              <CopyLinkButton url={article.canonical_url} compact hover />
              <span className="weekly-card__number">0{index + 1}</span>
              <p className="article-row__eyebrow">{article.source}{article.discovery_method === "ai_web" && formatDiscoveryDate(article.discovered_at) ? <small className="article-discovery-date" title="Von der KI hinzugefügt"> ({formatDiscoveryDate(article.discovered_at)})</small> : null} / {article.reading_minutes} Min. {!article.is_read ? <span className="new-badge">Neu</span> : null} {article.discovery_method === "ai_web" ? <span className="ai-badge">KI</span> : null} {article.access_status === "paywalled" ? "· Paywall" : ""}</p>
              <h3><Link href={`/artikel/${article.id}`}>{article.title}</Link></h3>
              {article.dek ? <p>{article.dek}</p> : null}
              <div className="weekly-card__footer"><span>{article.author}</span><Link href={`/artikel/${article.id}`} aria-label={`${article.title} lesen`}>Lesen →</Link></div>
            </article>
          ))}
        </div>
      </section>

      <section className="recommendations-section legacy-home-section" id="empfehlungen" aria-labelledby="recommendations-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Weiterdenken</p><h2 id="recommendations-title">Weitere Suggestions</h2></div>
          <div className="topic-strip" aria-label="Themenräume">{home.topics.slice(0, 4).map((topic) => <span key={topic.name}>{topic.name}</span>)}</div>
        </div>
        <div className="recommendations-grid">{recommendationArticles.map((article) => <ArticleRow key={article.id} article={article} />)}</div>
      </section>

      <HomeArticleSelections weeklyArticles={weeklyArticles} recommendationArticles={recommendationArticles} articlePool={articlePool} topics={home.topics} />

      {home.podcasts.length ? (
        <section className="podcast-section" aria-labelledby="podcast-title">
          <div className="section-heading section-heading--split">
            <div><p className="kicker">Für die Ohren</p><h2 id="podcast-title">Noch ein Umweg.</h2></div>
            <p>Bis zu drei Episoden, mit demselben Blick ausgewählt wie deine Texte.</p>
          </div>
          <PodcastRecommendations podcasts={home.podcasts} />
        </section>
      ) : null}

      <section className="reading-list" id="leselisten" aria-labelledby="weekend-title">
        <p className="kicker">Leseliste</p>
        <h2 id="weekend-title">Nimm dir ein langes Wochenende.</h2>
        <p>Eine ruhige Route durch Kultur, Technik und gesellschaftliche Fragen – zusammengestellt aus deinem Lesefluss.</p>
        <Link href="/archiv">Liste öffnen →</Link>
      </section>

    </main>
  );
}
