"use client";

import { useState } from "react";

import { dismissReadingInsight } from "../api";
import { ReadingProfile } from "../types";
import { SiteHeader } from "./SiteHeader";

const ratingLabels = { great: "Sehr", yes: "Ja", not_quite: "Nicht ganz", no: "Nein" } as const;

export function ReadingProfileView({ initial }: { initial: ReadingProfile }) {
  const [profile, setProfile] = useState(initial);

  async function dismiss(key: string) {
    await dismissReadingInsight(key);
    setProfile((current) => ({ ...current, insights: current.insights.filter((item) => item.key !== key) }));
  }

  return (
    <main className="page-shell reading-profile-shell">
      <SiteHeader active="profile" />
      <section className="reading-profile-intro">
        <h1>Was dérive über deinen Geschmack lernt.</h1>
        <p>Keine psychologische Charakteranalyse: nur nachvollziehbare Lesesignale, die du jederzeit entfernen kannst.</p>
      </section>
      <section className="reading-profile-stats" aria-label="Lesestatistik">
        <div><strong>{profile.stats.read_count}</strong><span>gelesene Texte</span></div>
        <div><strong>{profile.stats.saved_count}</strong><span>gemerkte Texte</span></div>
        <div><strong>{profile.stats.feedback_count}</strong><span>Rückmeldungen</span></div>
      </section>
      <section className="reading-profile-insights">
        <div className="section-heading"><div><p className="kicker">Dein Leseprofil</p><h2>Beobachtungen</h2></div><p>Diese Hinweise entstehen aus gelesenen, gemerkten und bewerteten Artikeln und fließen als weiche Signale in die KI-Suche ein.</p></div>
        {profile.insights.length ? <div className="reading-profile-insight-grid">{profile.insights.map((insight) => <article key={insight.key}><p>{insight.text}</p><small>{insight.basis}</small><button type="button" onClick={() => void dismiss(insight.key)}>Entfernen</button></article>)}</div> : <p className="reading-profile-empty">Noch keine Beobachtungen. Bewerte nach dem Lesen einen Text, damit dérive deinen Geschmack besser versteht.</p>}
      </section>
      <section className="reading-profile-feedback">
        <div className="section-heading"><div><p className="kicker">Rückblick</p><h2>Deine Rückmeldungen</h2></div><p>Freie Hinweise bleiben lokal und werden der KI nur als zusätzlicher Kontext übergeben.</p></div>
        {profile.feedback.length ? <div className="reading-profile-feedback-list">{profile.feedback.map((item) => <article key={item.id}><div><strong>{item.article_title}</strong><span>{item.source} · {ratingLabels[item.rating]}</span></div>{item.note ? <p>„{item.note}“</p> : null}</article>)}</div> : <p className="reading-profile-empty">Noch keine Rückmeldungen gespeichert.</p>}
      </section>
    </main>
  );
}
