import { AccountPanel } from "../components/AccountPanel";
import { SiteHeader } from "../components/SiteHeader";

export const dynamic = "force-dynamic";

export default function AccountPage() {
  return <main className="page-shell account-shell"><SiteHeader active={null} /><section className="account-intro"><p className="kicker">Privat & gemeinsam</p><h1>Dein Zugang.</h1><p>Lesespuren, KI-Erinnerungen und gespeicherte Texte gehören immer nur ihrem jeweiligen Konto.</p></section><AccountPanel /></main>;
}
