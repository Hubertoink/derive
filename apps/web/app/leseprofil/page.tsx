import { getReadingProfile } from "../server-api";
import { ReadingProfileView } from "../components/ReadingProfileView";

export const dynamic = "force-dynamic";

export default async function ReadingProfilePage() {
  return <ReadingProfileView initial={await getReadingProfile()} />;
}
