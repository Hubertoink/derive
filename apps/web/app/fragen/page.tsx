import { getReadingProfile } from "../server-api";
import { OpenQuestionsView } from "../components/OpenQuestionsView";
import { SiteHeader } from "../components/SiteHeader";

export const dynamic = "force-dynamic";

export default async function QuestionsPage() {
  const profile = await getReadingProfile();
  return (
    <main className="page-shell questions-shell">
      <SiteHeader active="questions" />
      <OpenQuestionsView initial={profile.questions.filter((question) => question.status === "open")} />
    </main>
  );
}
