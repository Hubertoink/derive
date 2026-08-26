import { IconBrandSpotify, IconExternalLink, IconHeadphones } from "@tabler/icons-react";
import Link from "next/link";

import { PodcastEpisode } from "../types";
import { SavePodcastButton } from "./SavePodcastButton";

function spotifySearch(episode: PodcastEpisode) {
  return `https://open.spotify.com/search/${encodeURIComponent(`${episode.show_name} ${episode.title}`)}`;
}

export function PodcastRecommendations({
  podcasts,
  compact = false,
  limit = 3,
}: {
  podcasts: PodcastEpisode[];
  compact?: boolean;
  limit?: number;
}) {
  if (!podcasts.length) return null;

  return (
    <div className={`podcast-grid${compact ? " podcast-grid--compact" : ""}`}>
      {podcasts.slice(0, limit).map((episode) => (
        <article className="podcast-card" key={episode.id} tabIndex={0}>
          <div className="article-actions"><SavePodcastButton podcastId={episode.id} initiallySaved={episode.is_saved} /></div>
          <IconHeadphones className="podcast-card__icon" size={22} aria-hidden="true" />
          <p className="article-row__eyebrow">
            {episode.show_name}{episode.duration_minutes ? ` · ${episode.duration_minutes} Min.` : ""}
          </p>
          <h3><Link href={`/podcast/${episode.id}`}>{episode.title}</Link></h3>
          {episode.description ? <p>{episode.description}</p> : null}
          {episode.curation_reason ? <p className="curator-note">Warum für dich: {episode.curation_reason}</p> : null}
          <div className="podcast-card__links">
            <a href={episode.spotify_url ?? spotifySearch(episode)} target="_blank" rel="noreferrer">
              <IconBrandSpotify size={17} aria-hidden="true" />
              {episode.spotify_url ? "Auf Spotify" : "Bei Spotify suchen"}
            </a>
            <a href={episode.canonical_url} target="_blank" rel="noreferrer">
              Original <IconExternalLink size={14} aria-hidden="true" />
            </a>
            <Link href={`/podcast/${episode.id}`}>Details →</Link>
          </div>
        </article>
      ))}
    </div>
  );
}
