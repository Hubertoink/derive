"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { clearDiscoveryChat, getDiscovery } from "../api";
import { Article, DiscoveryChatStatus, DiscoveryStatus, PodcastEpisode } from "../types";
import { PodcastRecommendations } from "./PodcastRecommendations";
import { SaveArticleButton } from "./SaveArticleButton";
import { useBackgroundOperations } from "./BackgroundOperations";

type ChatMode = "research" | "chat";

export function CuratorChat({
  initial,
  onUseProfile,
  onResearchFinished,
}: {
  initial: DiscoveryChatStatus;
  onUseProfile: (profile: string) => void;
  onResearchFinished: (status: DiscoveryStatus) => void;
}) {
  const [status, setStatus] = useState(initial);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [researchArticles, setResearchArticles] = useState<Article[]>([]);
  const [researchPodcasts, setResearchPodcasts] = useState<PodcastEpisode[]>([]);
  const [maxArticles, setMaxArticles] = useState(3);
  const [maxPodcasts, setMaxPodcasts] = useState<"auto" | "0" | "1" | "2" | "3">("auto");
  const [breadth, setBreadth] = useState<"focused" | "balanced" | "expansive">("balanced");
  const [mode, setMode] = useState<ChatMode>("research");
  const { startChat, startResearch } = useBackgroundOperations();
  const seenUserMessages = new Set<string>();
  const visibleMessages = status.messages.filter((item, index, all) => {
    if (item.role === "user") {
      if (seenUserMessages.has(item.content)) return false;
      seenUserMessages.add(item.content);
    }
    return all.findIndex((candidate) => candidate.role === item.role && candidate.content === item.content) === index;
  });

  async function send(event: FormEvent) {
    event.preventDefault();
    if (mode === "research") {
      await research();
      return;
    }
    const value = message.trim();
    if (!value || busy) return;
    setBusy(true);
    setNotice("");
    setMessage("");
    try {
      setStatus(await startChat(value));
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        setMessage(value);
        setNotice("Der Chat wurde abgebrochen.");
        return;
      }
      setMessage(value);
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function research() {
    const value = message.trim();
    if (value.length < 10 || busy) return;
    const lowered = value.toLocaleLowerCase("de-DE");
    const asksForPodcasts = lowered.includes("podcast") && /(bitte|suche|finde|empf|möchte|will|gern|kannst|könntest)/.test(lowered);
    const asksForTexts = /\b(artikel|text|texte|reportage|essay|studie|aufsatz|lektüre)\b/.test(lowered);
    const requestedArticleMax = Math.max(1, maxArticles);
    setBusy(true);
    setNotice("");
    try {
      const result = await startResearch(value, requestedArticleMax, maxPodcasts === "auto" ? null : Number(maxPodcasts), breadth);
      setMessage("");
      setStatus(result.chat);
      setResearchArticles(result.articles);
      setResearchPodcasts(result.podcasts);
      onResearchFinished(result.discovery);
      const resultCount = result.articles.length + result.podcasts.length;
      setNotice(resultCount ? `${result.articles.length} Texte und ${result.podcasts.length} Podcasts sind bereit.` : "Es wurden keine neuen, passenden Originalquellen gefunden.");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        setNotice("Die Recherche wurde abgebrochen. Bereits gespeicherte Ergebnisse bleiben erhalten.");
        return;
      }
      const message = (error as Error).message || "Die Recherche konnte nicht abgeschlossen werden.";
      if (!/returned 5\d\d|network|fetch|load failed/i.test(message)) {
        setNotice(message);
        return;
      }
      try {
        // A completed search can still have been committed before a proxy or
        // late response error. Recover the persisted results so the user does
        // not need to reload the whole page to see them.
        const recovered = await getDiscovery();
        setResearchArticles(recovered.articles);
        setResearchPodcasts(recovered.podcasts);
        onResearchFinished(recovered);
        const recoveredCount = recovered.articles.length + recovered.podcasts.length;
        setNotice(recoveredCount
          ? `${recoveredCount} gespeicherte Ergebnisse geladen. Die Recherche ist abgeschlossen.`
          : message);
      } catch {
        setNotice(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    try {
      await clearDiscoveryChat();
      setStatus((current) => ({ ...current, messages: [] }));
      setNotice("Unterhaltung gelöscht.");
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="curator-chat" aria-labelledby="curator-chat-title">
      <div className="curator-chat__heading">
        <div><p className="kicker">KI-Kurator</p><h2 id="curator-chat-title">{mode === "research" ? "Recherche auf Wunsch" : "Gemeinsam genauer werden"}</h2></div>
        <div className="curator-chat__heading-actions">
          <div className="curator-mode-toggle" role="tablist" aria-label="KI-Modus">
            <button type="button" role="tab" aria-selected={mode === "research"} className={mode === "research" ? "is-active" : ""} onClick={() => setMode("research")}>Recherche</button>
            <button type="button" role="tab" aria-selected={mode === "chat"} className={mode === "chat" ? "is-active" : ""} onClick={() => setMode("chat")}>Chat</button>
          </div>
          {status.messages.length ? <button type="button" onClick={clear} disabled={busy}>Verlauf löschen</button> : null}
        </div>
      </div>
      <div className="curator-chat__messages" aria-live="polite">
        {!status.messages.length ? (
          <div className="chat-message chat-message--assistant">
            <span>dérive</span>
            <p>{mode === "research" ? "Beschreibe dein Thema oder deine konkrete Frage. Ich suche bis zu deiner gewählten Artikelzahl passende Originalquellen und lege sie direkt im Archiv ab." : "Welche Art von Reportagen soll ich für dich finden? Wir können Themen, Regionen, Ton, Perspektiven und Quellen Schritt für Schritt eingrenzen. Deine bisherigen Angaben bleiben als Kontext erhalten."}</p>
          </div>
        ) : null}
        {visibleMessages.map((item) => (
          <div className={`chat-message chat-message--${item.role}`} key={item.id}>
            <span>{item.role === "assistant" ? "dérive" : "Du"}</span>
            <p>{item.content}</p>
            {item.profile_suggestion ? <button type="button" onClick={() => onUseProfile(item.profile_suggestion!)}>Als Ergänzung übernehmen</button> : null}
          </div>
        ))}
        {busy ? <div className="chat-message chat-message--assistant"><span>dérive</span><p>Denkt nach …</p></div> : null}
      </div>
      {researchArticles.length || researchPodcasts.length ? (
        <div className="chat-research-results" aria-label="Ergebnis der Ad-hoc-Recherche">
          <p className="kicker">Ad-hoc-Recherche · bis zu {maxArticles} Texte</p>
          {researchArticles.map((article) => (
            <article key={article.id} tabIndex={0}>
              <div className="article-actions"><SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} /></div>
              <p>{article.source} · ca. {article.reading_minutes} Min. {article.access_status === "paywalled" ? "· Paywall möglich" : ""}</p>
              <h3><a href={article.canonical_url} target="_blank" rel="noreferrer">{article.title} ↗</a></h3>
              {article.dek ? <span>{article.dek}</span> : null}
            </article>
          ))}
          {researchPodcasts.length ? (
            <div className="chat-research-podcasts">
              <p className="kicker">Podcast- & Audio-Longread-Funde</p>
              <PodcastRecommendations podcasts={researchPodcasts} compact />
            </div>
          ) : null}
        </div>
      ) : null}
      <form className="curator-chat__form" onSubmit={send}>
        <label className="sr-only" htmlFor="curator-message">Nachricht an den KI-Kurator</label>
        <textarea id="curator-message" rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder={mode === "research" ? "Zum Beispiel: Ich habe einen Podcast über Philip Manow gehört – suche mir drei fundierte Texte oder akademische Beiträge dazu." : "Zum Beispiel: Mich interessieren weiterhin europäische Perspektiven, aber bitte mit mehr historischen Reportagen."} disabled={busy || !status.provider_ready} />
        <div className="curator-chat__actions">
          <button type="submit" disabled={busy || !status.provider_ready || message.trim().length < (mode === "research" ? 10 : 1)}>{mode === "research" ? (busy ? "Suche läuft …" : "Recherche starten") : "Senden"}</button>
          {mode === "chat" ? <button type="button" className="button-quiet" onClick={() => setMode("research")} disabled={busy}>Zur Recherche wechseln</button> : null}
        </div>
      </form>
      {mode === "research" ? <div className="chat-research-controls" aria-label="Umfang der Ad-hoc-Recherche">
        <label>Max. Artikel
          <input type="number" min={1} max={12} value={maxArticles} onChange={(event) => setMaxArticles(Math.max(1, Math.min(12, Number(event.target.value) || 1)))} disabled={busy || !status.provider_ready} />
        </label>
        <label>Streuung
          <select value={breadth} onChange={(event) => setBreadth(event.target.value as typeof breadth)} disabled={busy || !status.provider_ready}>
            <option value="focused">Fokussiert</option>
            <option value="balanced">Ausgewogen</option>
            <option value="expansive">Horizont erweitern</option>
          </select>
        </label>
        <label>Podcasts & Audio-Longreads
          <select value={maxPodcasts} onChange={(event) => setMaxPodcasts(event.target.value as typeof maxPodcasts)} disabled={busy || !status.provider_ready}>
            <option value="auto">Aus Prompt</option>
            <option value="0">Keine</option>
            <option value="1">1 Empfehlung</option>
            <option value="2">2 Empfehlungen</option>
            <option value="3">3 Empfehlungen</option>
          </select>
        </label>
        <p>{breadth === "focused" ? "Tiefe vor Vielfalt." : breadth === "expansive" ? "dérive sucht bewusst auch angrenzende Perspektiven." : "Mehrere Perspektiven, eng am Thema."}</p>
      </div> : null}
      {!status.provider_ready ? <p className="provider-note">Richte zuerst unter <Link href="/einstellungen">Einstellungen</Link> einen KI-Provider ein.</p> : null}
      {notice ? <p className="discovery-notice" role="status">{notice}</p> : null}
    </section>
  );
}
