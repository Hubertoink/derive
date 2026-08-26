import { getArticles } from "../server-api";
import { ArchiveBrowser } from "../components/ArchiveBrowser";
import { SiteHeader } from "../components/SiteHeader";

export const dynamic = "force-dynamic";

export default async function ArchivePage() {
  const articles = await getArticles();

  return (
    <main className="page-shell archive-shell">
      <SiteHeader active="archive" />

      <section className="archive-intro" aria-labelledby="archive-title">
        <h1 id="archive-title">Dein Archiv.</h1>
        <p>{articles.length} {articles.length === 1 ? "Text" : "Texte"}, chronologisch aus deinen KI-Funden gesammelt.</p>
      </section>

      <ArchiveBrowser articles={articles} />
    </main>
  );
}
