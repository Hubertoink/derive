import { IconBrandSpotify, IconExternalLink, IconHeadphones } from "@tabler/icons-react";
import { getPodcast } from "../../server-api";
import { SavePodcastButton } from "../../components/SavePodcastButton";
import { SiteHeader } from "../../components/SiteHeader";
import { PreferenceFeedbackForm } from "../../components/PreferenceFeedbackForm";
import { PodcastEpisode } from "../../types";

export const dynamic = "force-dynamic";

function spotifySearch(episode: PodcastEpisode) {
  return `https://open.spotify.com/search/${encodeURIComponent(`${episode.show_name} ${episode.title}`)}`;
}

function formatDate(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("de-DE", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}

export default async function PodcastPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const episode = await getPodcast(id);
  const published = formatDate(episode.published_at);

  return (
    <main className="reader-shell">
      <SiteHeader active="home" />
      <article className="reader podcast-reader">
        <IconHeadphones className="podcast-reader__icon" size={28} aria-hidden="true" />
        <p className="kicker">{episode.show_name}</p>
        <h1>{episode.title}</h1>
        {episode.description ? <p className="reader__dek">{episode.description}</p> : null}
        <div className="reader__meta">
          {episode.duration_minutes ? <span>{episode.duration_minutes} Min.</span> : null}
          {published ? <span>{published}</span> : null}
          <span className="ai-badge">KI-Kurator</span>
        </div>
        <div className="reader-actions">
          <SavePodcastButton podcastId={episode.id} initiallySaved={episode.is_saved} variant="reader" />
        </div>
        {episode.curation_reason ? (
          <section className="podcast-reader__reason" aria-labelledby="podcast-reason-title">
            <p className="kicker" id="podcast-reason-title">Warum für dich</p>
            <p>{episode.curation_reason}</p>
          </section>
        ) : null}
        <PreferenceFeedbackForm kind="podcast" targetId={episode.id} />
        <section className="podcast-reader__source" aria-labelledby="podcast-source-title">
          <p className="kicker" id="podcast-source-title">Weiterhören</p>
          <p>Audio und Beschreibung bleiben bei der Originalplattform.</p>
          <div className="podcast-reader__links">
            <a href={episode.spotify_url ?? spotifySearch(episode)} target="_blank" rel="noreferrer">
              <IconBrandSpotify size={18} aria-hidden="true" />
              {episode.spotify_url ? "Auf Spotify" : "Bei Spotify suchen"}
            </a>
            <a href={episode.canonical_url} target="_blank" rel="noreferrer">
              Episode öffnen <IconExternalLink size={15} aria-hidden="true" />
            </a>
          </div>
        </section>
      </article>
    </main>
  );
}
