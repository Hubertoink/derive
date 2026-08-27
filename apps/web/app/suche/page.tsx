import { getArticles } from "../server-api";
import { SearchBrowser } from "../components/SearchBrowser";
import { SiteHeader } from "../components/SiteHeader";

export const dynamic = "force-dynamic";

export default async function SearchPage() {
  const articles = await getArticles();

  return (
    <main className="page-shell search-shell">
      <SiteHeader active={null} />
      <section className="search-intro" aria-labelledby="search-title">
        <p className="kicker">Im Archiv finden</p>
        <h1 id="search-title">Suche.</h1>
        <p>Finde schnell zurück zu einer Reportage, einer Quelle oder einer Stimme.</p>
      </section>
      <SearchBrowser articles={articles} />
    </main>
  );
}
