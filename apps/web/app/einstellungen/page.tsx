import { getSetup } from "../server-api";
import { SetupWizard } from "../components/SetupWizard";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const setup = await getSetup();
  return (
    <SetupWizard initial={setup} />
  );
}
