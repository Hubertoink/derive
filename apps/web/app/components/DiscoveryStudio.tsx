"use client";

import Link from "next/link";
import { useState } from "react";

import { getDiscovery, runDiscovery, saveDiscoveryProfile, updateDiscoverySource } from "../api";
import { Article, DiscoveryChatStatus, DiscoveryProfile, DiscoveryStatus } from "../types";
import { CopyLinkButton } from "./CopyLinkButton";
import { CuratorChat } from "./CuratorChat";
import { formatDiscoveryDate } from "./ArticleRow";
import { PodcastRecommendations } from "./PodcastRecommendations";
import { ReflectionQuestions } from "./ReflectionQuestions";
import { SaveArticleButton } from "./SaveArticleButton";

const suggestions = [
  "Europäische Technologiepolitik, Macht und Gesellschaft",
  "Klimaanpassung – nah an Menschen und konkreten Orten",
  "Wissenschaftliche Reportagen mit überraschender Erzählperspektive",
];

const frequencyLabels = {
  manual: "nur auf Wunsch",
  interval: "nach Zeitplan",
  daily: "täglich",
  every_3_days: "alle drei Tage",
  weekly: "wöchentlich",
} as const;

function formatDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Berlin" }).format(new Date(value));
}

function formatTokens(value: number) {
  return new Intl.NumberFormat("de-DE").format(value);
}

function formatIntervalDays(days: number) {
  return `alle ${days} ${days === 1 ? "Tag" : "Tage"}`;
}

export function DiscoveryStudio({ initial, initialChat, reflectionArticles }: { initial: DiscoveryStatus; initialChat: DiscoveryChatStatus; reflectionArticles: Article[] }) {
  const [status, setStatus] = useState(initial);
  const [profile, setProfile] = useState<DiscoveryProfile>(() => ({
    ...initial.profile,
    deprioritized_sources: initial.profile.deprioritized_sources ?? [],
    frequency: initial.profile.frequency === "manual" ? "manual" : "interval",
    interval_days: initial.profile.interval_days ?? (initial.profile.frequency === "every_3_days" ? 3 : initial.profile.frequency === "weekly" ? 7 : 1),
    delivery_time: initial.profile.delivery_time ?? "09:00",
    timezone: initial.profile.timezone ?? "Europe/Berlin",
  }));
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const [sourceBusy, setSourceBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [sourceDraft, setSourceDraft] = useState("");
  const [progress, setProgress] = useState<{ phase: "articles" | "podcasts"; batch: number; batches: number; found: number; podcasts: number; tokens: number } | null>(null);
  const deprioritizedSources = profile.deprioritized_sources ?? [];

  async function addSource() {
    const source = sourceDraft.trim().replace(/,$/, "").trim();
    if (!source || deprioritizedSources.some((existing) => existing.toLowerCase() === source.toLowerCase())) {
      setSourceDraft("");
      return;
    }
    const nextSources = [...deprioritizedSources, source];
    const nextProfile = { ...profile, deprioritized_sources: nextSources };
    update("deprioritized_sources", nextSources);
    setSourceDraft("");
    setBusy("save");
    try {
      const next = await saveDiscoveryProfile(nextProfile);
      setStatus(next);
      setProfile(next.profile);
      setNotice("Quelle gespeichert und für die KI-Suche vorgemerkt.");
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function removeSource(source: string) {
    update("deprioritized_sources", deprioritizedSources.filter((existing) => existing !== source));
  }

  async function changeSourceStatus(domain: string, status: "active" | "deprioritized" | "excluded") {
    setSourceBusy(domain);
    try {
      const next = await updateDiscoverySource(domain, status);
      setStatus(next);
      setProfile(next.profile);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setSourceBusy(null);
    }
  }

  function update<K extends keyof DiscoveryProfile>(key: K, value: DiscoveryProfile[K]) {
    setProfile((current) => ({ ...current, [key]: value }));
  }

  function appendToProfile(addition: string) {
    const prefix = profile.prompt.trim();
    update("prompt", `${prefix}${prefix ? "\n\nZusätzlich: " : ""}${addition.trim()}`);
    setNotice("Als Ergänzung vorgemerkt. Dein bisheriges Suchprofil bleibt erhalten.");
  }

  function useSuggestedProfile(prompt: string) {
    appendToProfile(prompt);
  }

  function markArticleRead(articleId: number) {
    setStatus((current) => ({
      ...current,
      articles: current.articles.map((article) => (
        article.id === articleId ? { ...article, is_read: true } : article
      )),
    }));
    void fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/articles/${articleId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ is_read: true }),
    });
  }

  async function save() {
    setBusy("save");
    setNotice("");
    try {
      const next = await saveDiscoveryProfile(profile);
      setStatus(next);
      setProfile(next.profile);
      setNotice("Dein Suchprofil ist gespeichert.");
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function searchNow() {
    setBusy("run");
    let partialImported = 0;
    setProgress({ phase: "articles", batch: 0, batches: 1, found: 0, podcasts: 0, tokens: 0 });
    setNotice("dérive sucht und prüft gerade passende Originalquellen …");
    try {
      const saved = await saveDiscoveryProfile(profile);
      setStatus(saved);
      setProfile(saved.profile);
      const next = await runDiscovery(undefined, (event) => {
        partialImported = Math.max(partialImported, event.found_count ?? 0);
        setProgress({ phase: event.phase ?? "articles", batch: event.batch, batches: event.batches, found: event.found_count, podcasts: event.podcasts_found ?? 0, tokens: event.total_tokens });
        setStatus((current) => {
          const known = new Set(current.articles.map((article) => article.id));
          const newArticles = event.found.filter((article) => !known.has(article.id));
          const knownPodcasts = new Set(current.podcasts.map((podcast) => podcast.id));
          const newPodcasts = (event.podcasts ?? []).filter((podcast) => !knownPodcasts.has(podcast.id));
          return { ...current, articles: [...newArticles, ...current.articles].slice(0, 12), podcasts: [...newPodcasts, ...current.podcasts].slice(0, 3) };
        });
        setNotice(event.phase === "podcasts"
          ? `Podcast-Suche abgeschlossen: ${event.podcasts_found ?? 0} neue Empfehlungen · ${formatTokens(event.total_tokens)} Token verarbeitet.`
          : `Quellensuche ${event.batch}/${event.batches}: ${event.found_count} Artikel gefunden · ${formatTokens(event.total_tokens)} Token verarbeitet.`);
      });
      setStatus(next);
      setProfile(next.profile);
      setNotice(
        next.recovered
          ? `${next.imported || partialImported} Artikel wurden bereits gespeichert. Die Verbindung wurde unterbrochen; du kannst die Suche erneut starten.`
          : next.imported
          ? `${next.imported} neue ${next.imported === 1 ? "Empfehlung" : "Empfehlungen"} gefunden.`
          : "Heute ist nichts Neues durch den Qualitätsfilter gekommen."
      );
    } catch (error) {
      const rawMessage = (error as Error).message || "Die KI-Suche konnte nicht abgeschlossen werden.";
      const message = /network|fetch|load failed/i.test(rawMessage)
        ? "Die Verbindung zur KI-Suche wurde unterbrochen."
        : rawMessage;
      try {
        const recovered = await getDiscovery();
        setStatus(recovered);
        setProfile(recovered.profile);
        setNotice(partialImported
          ? `${partialImported} Artikel wurden gespeichert. Die Verbindung wurde unterbrochen; du kannst die Suche erneut starten.`
          : message);
      } catch {
        setNotice(message);
      }
    } finally {
      setBusy(null);
      setProgress(null);
    }
  }

  return (
    <div className="discovery-layout">
      <section className="discovery-intro">
        <p className="kicker">Dein KI-Kurator</p>
        <h1>Beschreib, was du wirklich lesen willst.</h1>
        <p>
          dérive verbindet deine Leseinteressen mit einer gezielten Websuche nach
          langen, sorgfältig recherchierten Texten. Jede Empfehlung bleibt mit
          ihrer Originalquelle verbunden.
        </p>
      </section>

      <CuratorChat initial={initialChat} onUseProfile={useSuggestedProfile} onResearchFinished={setStatus} />

      <section className="discovery-conversation" aria-labelledby="discovery-request-title">
        <div className="assistant-note">
          <span aria-hidden="true">✦</span>
          <p>
            Ich suche nach Reportagen, Essays und Analysen, die zu deinem Profil passen.
            Bei Webfunden führe ich dich direkt zum Original; Volltexte werden nicht kopiert.
          </p>
        </div>
        <label className="discovery-request">
          <span id="discovery-request-title">Dein Wunsch an dérive</span>
          <textarea
            rows={5}
            value={profile.prompt}
            onChange={(event) => update("prompt", event.target.value)}
            placeholder="Zum Beispiel: lange Reportagen über die gesellschaftlichen Folgen neuer Technologien, gern aus Europa …"
          />
        </label>
        <p className="profile-memory-note">Dein bestehendes Profil bleibt Kontext. Über die Vorschläge oder den Mehrturn-Chat fügst du neue Wünsche als Ergänzung hinzu.</p>
        <div className="prompt-suggestions" aria-label="Beispiele">
          {suggestions.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => appendToProfile(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
        <section className="source-preferences" aria-labelledby="source-preferences-title">
          <div className="source-preferences__heading">
            <div>
              <span id="source-preferences-title">Quellen, die du ohnehin liest</span>
              <p>Diese Publikationen werden seltener empfohlen, bleiben aber bei außergewöhnlich passenden Texten möglich.</p>
            </div>
            {deprioritizedSources.length ? <span className="source-preferences__count">{deprioritizedSources.length} {deprioritizedSources.length === 1 ? "Quelle" : "Quellen"}</span> : null}
          </div>
          {deprioritizedSources.length ? (
            <div className="source-badges" aria-label="Ausgewählte Quellen">
              {deprioritizedSources.map((source) => (
                <span className="source-badge" key={source}>
                  <span>{source}</span>
                  <button type="button" onClick={() => removeSource(source)} aria-label={`${source} entfernen`} title="Quelle entfernen">×</button>
                </span>
              ))}
            </div>
          ) : <p className="source-preferences__empty">Noch keine Quellen hinterlegt.</p>}
          <div className="source-add">
            <label htmlFor="source-draft">Quelle hinzufügen</label>
            <div className="source-add__row">
              <input
                id="source-draft"
                type="text"
                value={sourceDraft}
                onChange={(event) => setSourceDraft(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addSource(); } }}
                placeholder="z. B. zeit.de"
                autoComplete="off"
              />
              <button type="button" onClick={addSource} disabled={!sourceDraft.trim() || busy !== null}>Hinzufügen</button>
            </div>
          </div>
        </section>
        {status.sources?.some((source) => source.origin === "learned" || source.observed_count > 0) ? (
          <section className="source-memory" aria-labelledby="source-memory-title">
            <div className="source-preferences__heading">
              <div>
                <span id="source-memory-title">Automatisch entdeckte Quellen</span>
                <p>dérive merkt sich passende Publikationen, rotiert sie und lässt bei jedem Lauf Raum für neue Quellen.</p>
              </div>
              <span className="source-preferences__count">{status.sources.filter((source) => source.origin === "learned" || source.observed_count > 0).length}</span>
            </div>
            <div className="source-memory-list">
              {status.sources.filter((source) => source.origin === "learned" || source.observed_count > 0).map((source) => (
                <article className={`source-memory-card source-memory-card--${source.status}`} key={source.domain}>
                  <div>
                    <strong>{source.name}</strong>
                    <small>{source.domain} · {source.observed_count} Treffer{source.positive_count ? ` · ${source.positive_count} positiv` : ""}</small>
                  </div>
                  <div className="source-memory-card__actions">
                    {source.status !== "active" ? <button type="button" disabled={sourceBusy === source.domain} onClick={() => changeSourceStatus(source.domain, "active")}>Bevorzugen</button> : null}
                    {source.status !== "deprioritized" ? <button type="button" disabled={sourceBusy === source.domain} onClick={() => changeSourceStatus(source.domain, "deprioritized")}>Seltener</button> : null}
                    {source.status !== "excluded" ? <button type="button" disabled={sourceBusy === source.domain} onClick={() => changeSourceStatus(source.domain, "excluded")}>Ausschließen</button> : null}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </section>

      <aside className="discovery-controls" aria-label="Suchrhythmus und Filter">
        <p className="kicker">Rhythmus & Qualität</p>
        <label>
          <span>Neue Auswahl</span>
          <select value={profile.frequency === "manual" ? "manual" : "interval"} onChange={(event) => update("frequency", event.target.value as DiscoveryProfile["frequency"])}>
            <option value="interval">Nach Zeitplan</option>
            <option value="manual">Nur auf Wunsch</option>
          </select>
        </label>
        {profile.frequency !== "manual" ? (
          <div className="discovery-number-fields discovery-schedule-fields">
            <label><span>Alle X Tage</span><input type="number" min={1} max={30} value={profile.interval_days} onChange={(event) => update("interval_days", Math.max(1, Math.min(30, Number(event.target.value) || 1)))} /></label>
            <label><span>Uhrzeit</span><input type="time" value={profile.delivery_time} onChange={(event) => update("delivery_time", event.target.value)} /></label>
          </div>
        ) : null}
        <div className="discovery-number-fields">
          <label><span>Mind. Minuten</span><input type="number" min={5} max={120} value={profile.min_minutes} onChange={(event) => update("min_minutes", Number(event.target.value))} /></label>
          <label><span>Texte je Lauf</span><input type="number" min={1} max={12} value={profile.max_articles} onChange={(event) => update("max_articles", Number(event.target.value))} /></label>
        </div>
        <label className="discovery-check">
          <input type="checkbox" checked={profile.include_paywalled} onChange={(event) => update("include_paywalled", event.target.checked)} />
          <span>Auch herausragende Paywall-Artikel anzeigen</span>
        </label>
        <label className="source-preferences-legacy">
          <span>Quellen, die du ohnehin liest</span>
          <input
            type="text"
            value={deprioritizedSources.join(", ")}
            onChange={(event) => update("deprioritized_sources", event.target.value.split(",").map((source) => source.trim()).filter(Boolean))}
            placeholder="z. B. zeit.de, newyorker.com"
          />
          <small>Diese Quellen werden seltener empfohlen, bleiben aber für außergewöhnlich passende Texte möglich.</small>
        </label>
        <div className="discovery-actions">
          <button className="button-quiet" type="button" onClick={save} disabled={busy !== null}>Profil speichern</button>
          <button className="button-primary" type="button" onClick={searchNow} disabled={busy !== null || !status.provider_ready}>
            {busy === "run" ? "Suche läuft …" : "Jetzt suchen"}
          </button>
        </div>
        {!status.provider_ready ? (
          <p className="provider-note">
            Für die Websuche muss die OpenAI-Verbindung unter <Link href="/einstellungen">Einstellungen</Link> vollständig eingerichtet sein.
          </p>
        ) : null}
        {progress ? <p className="discovery-progress" role="status"><span className="discovery-progress__dot" aria-hidden="true" /> {progress.phase === "podcasts" ? `Podcast-Suche · ${progress.podcasts} Empfehlungen gefunden` : `Quellensuche ${progress.batch}/${progress.batches} · ${progress.found} Artikel gefunden`} · {formatTokens(progress.tokens)} Token</p> : null}
        {notice && !progress ? <p className="discovery-notice" role="status">{notice}</p> : null}
      </aside>

      <section className="discovery-activity" aria-labelledby="discovery-activity-title">
        <div>
          <p className="kicker">Automatik & Erinnerung</p>
          <h2 id="discovery-activity-title">Die Suche bleibt in Bewegung.</h2>
        </div>
        <div className="discovery-activity__copy">
          {status.automation.enabled ? (
            <p>Solange dein Docker-Stack läuft, prüft der dérive-Worker jede Minute, ob deine <strong>{profile.frequency === "manual" ? frequencyLabels.manual : `${formatIntervalDays(profile.interval_days)} um ${profile.delivery_time}`}</strong> Suche fällig ist. Zusätzlich füllt er den Vorrat bei Bedarf automatisch etwa alle {status.automation.background_interval_hours} Stunden mit passenden Artikeln auf. Der nächste reguläre Lauf beginnt frühestens {status.automation.next_due_at ? formatDate(status.automation.next_due_at) : "nach dem Start des Workers"} ({profile.timezone}).</p>
          ) : (
            <p>Die automatische Suche ist aus. Wähle einen Rhythmus und richte OpenAI vollständig ein, damit der Docker-Worker neue Texte für dich suchen kann.</p>
          )}
          <p className="discovery-memory"><strong>Memory:</strong> dérive bewahrt dein Suchprofil, deinen Chat-Verlauf und passende Publikationen lokal. Etablierte Quellen werden rotierend genutzt; mindestens ein Teil jeder Suche bleibt offen für neue Entdeckungen.</p>
        </div>
        <div className="discovery-run-log" aria-label="Suchverlauf">
          <h3>Letzte Suchläufe</h3>
          {status.runs.length ? (
            <ol>
              {status.runs.slice(0, 4).map((run) => (
                <li key={run.id} className={run.status === "success" ? "is-success" : "is-failed"}>
                  <time dateTime={run.ran_at}>{formatDate(run.ran_at)}</time>
                  <span>{run.trigger === "background" ? "Vorratssuche" : run.trigger === "automatic" ? "Automatisch" : run.trigger === "chat" ? "Chat-Recherche" : "Manuell"}</span>
                  <strong>{run.status === "success" ? `${run.imported_count} neue ${run.imported_count === 1 ? "Empfehlung" : "Empfehlungen"}${run.total_tokens ? ` (${formatTokens(run.total_tokens)} Token)` : ""}` : "Suche fehlgeschlagen"}</strong>
                  {run.message ? <p>{run.message}</p> : null}
                </li>
              ))}
            </ol>
          ) : <p>{profile.last_run_at ? `Der Verlauf beginnt mit dem nächsten Lauf. Letzter erfolgreicher Lauf: ${formatDate(profile.last_run_at)}.` : "Noch kein Suchlauf protokolliert."}</p>}
        </div>
      </section>

      <ReflectionQuestions initial={reflectionArticles} />

      <section className="discovery-results" aria-labelledby="discovery-results-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Zuletzt entdeckt</p><h2 id="discovery-results-title">Neue Wege in Texte</h2></div>
          <p>{profile.last_run_at ? `Letzter erfolgreicher Lauf: ${formatDate(profile.last_run_at)}` : "Die erste Suche steht noch aus."}</p>
        </div>
        {status.articles.length ? (
          <div className="discovery-result-list">
            {status.articles.map((article) => (
              <article key={article.id} tabIndex={0}>
                <div className="article-actions">
                  <SaveArticleButton articleId={article.id} initiallySaved={article.is_saved} />
                  <CopyLinkButton url={article.canonical_url} compact hover />
                </div>
              <p className="article-row__eyebrow">{article.source}{formatDiscoveryDate(article.discovered_at) ? <small className="article-discovery-date"> ({formatDiscoveryDate(article.discovered_at)})</small> : null} · ca. {article.reading_minutes} Min. {!article.is_read ? <span className="new-badge">Neu</span> : null} <span className="ai-badge">KI</span> {article.access_status === "paywalled" ? <span className="access-badge">Paywall</span> : null}</p>
                <h3><a href={article.canonical_url} target="_blank" rel="noreferrer" onClick={() => markArticleRead(article.id)}>{article.title} ↗</a></h3>
                {article.dek ? <p>{article.dek}</p> : null}
                {article.curation_reason ? <p className="curator-note">Warum für dich: {article.curation_reason}</p> : null}
                {article.access_status === "paywalled" ? <div className="paywall-actions"><span>Abonnement kann erforderlich sein.</span></div> : null}
              </article>
            ))}
          </div>
        ) : <p className="empty-discovery">Noch keine KI-Funde. Starte eine Suche, sobald dein KI-Provider eingerichtet ist.</p>}
      </section>
      {status.podcasts.length ? (
        <section className="discovery-podcasts" aria-labelledby="discovery-podcast-title">
          <div className="section-heading section-heading--split">
            <div><p className="kicker">Für die Ohren</p><h2 id="discovery-podcast-title">Podcasts & Audio-Longreads</h2></div>
            <p>Metadaten und Links bleiben bei den Originalplattformen.</p>
          </div>
          <PodcastRecommendations podcasts={status.podcasts} compact />
        </section>
      ) : null}
    </div>
  );
}
