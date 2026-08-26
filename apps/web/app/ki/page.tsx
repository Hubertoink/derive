import { getArticles, getDiscovery, getDiscoveryChat, getReadingProfile } from "../server-api";
import { SiteHeader } from "../components/SiteHeader";
import { DiscoveryStudio } from "../components/DiscoveryStudio";

export const dynamic = "force-dynamic";

export default async function DiscoveryPage() {
  const [initial, initialChat, articles, readingProfile] = await Promise.all([
    getDiscovery(),
    getDiscoveryChat(),
    getArticles(),
    getReadingProfile(),
  ]);
  const answeredArticleIds = new Set(readingProfile.feedback.map((feedback) => feedback.article_id));
  const reflectionArticles = articles
    .filter((article) => article.is_read && !answeredArticleIds.has(article.id))
    .slice(0, 3);

  return (
    <main className="discovery-shell">
      <SiteHeader active="curator" />
      <DiscoveryStudio initial={initial} initialChat={initialChat} reflectionArticles={reflectionArticles} />
    </main>
  );
}
