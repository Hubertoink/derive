"use client";

import { ChangeEvent, useState } from "react";

import { saveSoul, updateReadingInsight } from "../api";
import { PreferenceReason, ReadingProfile } from "../types";
import { SiteHeader } from "./SiteHeader";

const ratingLabels = { great: "Sehr passend", yes: "Passend", not_quite: "Nicht ganz", no: "Unpassend" } as const;
const reasonLabels: Record<PreferenceReason, string> = {
  topic: "Thema", perspective: "Perspektive", depth: "Tiefe", style: "Stil", source: "Quelle",
  timing: "Zeitpunkt", too_shallow: "zu oberflächlich", too_familiar: "zu vertraut", too_current: "zu aktuell",
};
const soulTemplate = `# Meine kuratorische Haltung

## Was ich suche
Texte, Gespräche und Bilder, die …

## Qualität
Mir sind besonders wichtig …

## Ton und Form
Ich mag …

## Weniger davon
Bitte vermeide …

## Perspektiven
Zeige mir häufiger …

## Überraschung
Ein Teil der Auswahl darf mein bekanntes Profil verlassen, wenn dérive den Zusammenhang erklärt.`;

export function ReadingProfileView({ initial }: { initial: ReadingProfile }) {
  const [profile, setProfile] = useState(initial);
  const [soulDraft, setSoulDraft] = useState(initial.soul.markdown);
  const [artEnabled, setArtEnabled] = useState(initial.soul.art_enabled);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function setInsight(key: string, status: "confirmed" | "dismissed") {
    setBusy(true);
    try { setProfile(await updateReadingInsight(key, status)); } finally { setBusy(false); }
  }

  async function persistSoul() {
    setBusy(true);
    setNotice("");
    try {
      const next = await saveSoul(soulDraft, artEnabled);
      setProfile(next);
      setSoulDraft(next.soul.markdown);
      setNotice(`Kuratorische Haltung gespeichert · Revision ${next.soul.revision}.`);
    } catch (error) {
      setNotice((error as Error).message);
    } finally { setBusy(false); }
  }

  async function importSoul(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLocaleLowerCase().endsWith(".md")) {
      setNotice("Bitte eine Markdown-Datei mit der Endung .md wählen.");
      return;
    }
    setSoulDraft((await file.text()).slice(0, 12000));
    setNotice("Datei geladen. Prüfe den Inhalt und speichere ihn anschließend.");
    event.target.value = "";
  }

  function exportSoul() {
    const blob = new Blob([soulDraft], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "SOUL.md";
    link.click();
    URL.revokeObjectURL(url);
  }

  const allFeedback = [
    ...profile.feedback.map((item) => ({ ...item, title: item.article_title, kind: "Text" })),
    ...profile.podcast_feedback.map((item) => ({ ...item, kind: "Podcast" })),
    ...profile.artwork_feedback.map((item) => ({ ...item, kind: "Kunst" })),
  ];

  return (
    <main className="page-shell reading-profile-shell">
      <SiteHeader active="profile" />
      <section className="reading-profile-intro">
        <h1>Was dérive über deinen Geschmack lernt.</h1>
        <p>Deine Haltung bleibt bewusst gesetzt. Beobachtungen werden erst nach deiner Bestätigung zu Langzeiterinnerungen.</p>
      </section>

      <section className="soul-editor" aria-labelledby="soul-title">
        <div className="section-heading section-heading--split">
          <div><p className="kicker">Kuratorische Haltung</p><h2 id="soul-title">Deine SOUL.md</h2></div>
          <p>Diese Angaben haben Vorrang vor abgeleiteten Verhaltenssignalen. Dérive verändert sie niemals automatisch.</p>
        </div>
        <div className="soul-editor__grid">
          <div className="soul-editor__write">
            <label htmlFor="soul-markdown">Markdown</label>
            <textarea id="soul-markdown" rows={18} maxLength={12000} value={soulDraft} onChange={(event) => setSoulDraft(event.target.value)} placeholder={soulTemplate} />
            <div className="soul-editor__actions">
              <button type="button" onClick={() => setSoulDraft(soulTemplate)} disabled={busy}>Vorlage einsetzen</button>
              <label className="soul-file-button">Importieren<input type="file" accept=".md,text/markdown,text/plain" onChange={(event) => void importSoul(event)} /></label>
              <button type="button" onClick={exportSoul}>Exportieren</button>
              <button className="soul-save" type="button" onClick={() => void persistSoul()} disabled={busy}>{busy ? "Speichert …" : "Haltung speichern"}</button>
            </div>
            <label className="soul-art-toggle"><input type="checkbox" checked={artEnabled} onChange={(event) => setArtEnabled(event.target.checked)} /> Öffentliche Kunstwerke als visuelle Seitenblicke einbeziehen</label>
            {notice ? <p className="soul-editor__notice" role="status">{notice}</p> : null}
          </div>
          <aside className="soul-editor__preview">
            <p className="kicker">So erhält es der Kurator</p>
            <pre>{soulDraft || "Noch keine Haltung festgelegt."}</pre>
            <small>{soulDraft.length.toLocaleString("de-DE")} / 12.000 Zeichen · Revision {profile.soul.revision}</small>
            {profile.soul.revisions.length ? <div className="soul-revisions"><strong>Frühere Revisionen</strong>{profile.soul.revisions.map((revision) => <button type="button" key={revision.revision} onClick={() => setSoulDraft(revision.markdown)}>Revision {revision.revision} · {new Date(revision.created_at).toLocaleDateString("de-DE")}</button>)}</div> : null}
          </aside>
        </div>
      </section>

      <section className="reading-profile-stats" aria-label="Lesestatistik">
        <div><strong>{profile.stats.read_count}</strong><span>gelesene Texte</span></div>
        <div><strong>{profile.stats.saved_count}</strong><span>gemerkte Funde</span></div>
        <div><strong>{profile.stats.feedback_count}</strong><span>Rückmeldungen</span></div>
      </section>
      <section className="reading-profile-insights">
        <div className="section-heading"><div><p className="kicker">Transparentes Gedächtnis</p><h2>Beobachtungen prüfen</h2></div><p>Nur bestätigte Beobachtungen werden als starke Langzeiterinnerung an die KI übergeben.</p></div>
        {profile.insights.length ? <div className="reading-profile-insight-grid">{profile.insights.map((insight) => <article key={insight.key} className={insight.status === "confirmed" ? "is-confirmed" : ""}><p>{insight.text}</p><small>{insight.basis} · Sicherheit: {insight.confidence === "high" ? "hoch" : insight.confidence === "low" ? "niedrig" : "mittel"}</small><div><button type="button" disabled={busy || insight.status === "confirmed"} onClick={() => void setInsight(insight.key, "confirmed")}>{insight.status === "confirmed" ? "Bestätigt" : "Behalten"}</button><button type="button" disabled={busy} onClick={() => void setInsight(insight.key, "dismissed")}>Verwerfen</button></div></article>)}</div> : <p className="reading-profile-empty">Noch keine Beobachtungen. Ausdrückliches Feedback erzeugt hier nachvollziehbare Vorschläge.</p>}
      </section>
      {profile.questions.some((question) => question.status === "answered") ? <section className="reading-profile-questions">
        <div className="section-heading"><div><p className="kicker">Explizite Präferenzen</p><h2>Deine Antworten</h2></div><p>Diese Antworten werden bei künftigen Empfehlungen berücksichtigt und bleiben von deiner SOUL.md getrennt.</p></div>
        <div className="reading-profile-questions-list">{profile.questions.filter((question) => question.status === "answered").map((question) => <article key={question.key}><strong>{question.question}</strong><p>{question.answer ?? "Antwort gespeichert."}</p><small>{question.basis}</small></article>)}</div>
      </section> : null}
      <section className="reading-profile-feedback">
        <div className="section-heading"><div><p className="kicker">Rückblick</p><h2>Deine Rückmeldungen</h2></div><p>Texte, Podcasts und Kunst bleiben getrennte Signale und werden mit ihrer Herkunft gespeichert.</p></div>
        {allFeedback.length ? <div className="reading-profile-feedback-list">{allFeedback.map((item) => <article key={`${item.kind}-${item.id}`}><div><strong>{item.title}</strong><span>{item.kind} · {item.source} · {ratingLabels[item.rating]}</span></div>{item.reasons.length ? <small>{item.reasons.map((reason) => reasonLabels[reason]).join(" · ")}</small> : null}{item.note ? <p>„{item.note}“</p> : null}</article>)}</div> : <p className="reading-profile-empty">Noch keine Rückmeldungen gespeichert.</p>}
      </section>
    </main>
  );
}
