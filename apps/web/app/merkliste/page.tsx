import { getArticles, getPodcasts } from "../server-api";
import { PodcastRecommendations } from "../components/PodcastRecommendations";
import { SavedArticleGallery } from "../components/SavedArticleGallery";
import { SiteHeader } from "../components/SiteHeader";

export const dynamic = "force-dynamic";

export default async function SavedArticlesPage() {
  const [allArticles, allPodcasts] = await Promise.all([getArticles(), getPodcasts()]);
  const articles = allArticles.filter((article) => article.is_saved);
  const podcasts = allPodcasts.filter((podcast) => podcast.is_saved);
  const savedCount = articles.length + podcasts.length;

  return (
    <main className="page-shell saved-shell">
      <SiteHeader active={null} />
      <section className="saved-intro" aria-labelledby="saved-title">
        <p className="kicker">Für später bewahrt</p>
        <h1 id="saved-title">Deine Merkliste.</h1>
        <p>{savedCount ? `${savedCount} ${savedCount === 1 ? "Fund wartet" : "Funde warten"} auf deine Zeit.` : "Noch ist nichts gemerkt."}</p>
      </section>
      <section className="saved-list" aria-label="Gemerkt">
        {articles.length ? <SavedArticleGallery initial={articles} /> : null}
      </section>
      {podcasts.length ? (
        <section className="saved-podcasts" aria-labelledby="saved-podcasts-title">
          <p className="kicker">Für die Ohren bewahrt</p>
          <h2 id="saved-podcasts-title">Gemerkte Audio-Empfehlungen</h2>
          <PodcastRecommendations podcasts={podcasts} limit={podcasts.length} />
        </section>
      ) : null}
      {!articles.length && !podcasts.length ? <p className="archive-empty saved-empty">Markiere Artikel, Podcasts oder Audio-Longreads mit „Merken“, um sie hier wiederzufinden.</p> : null}
    </main>
  );
}
