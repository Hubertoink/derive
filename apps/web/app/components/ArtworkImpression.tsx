import { IconExternalLink } from "@tabler/icons-react";

import { Artwork } from "../types";
import { PreferenceFeedbackForm } from "./PreferenceFeedbackForm";

export function ArtworkImpression({ artwork }: { artwork: Artwork }) {
  const facts = [artwork.artist_display, artwork.date_display, artwork.medium_display, artwork.place_of_origin].filter(Boolean);
  return (
    <section className="artwork-impression" aria-labelledby="artwork-impression-title">
      <div className="section-heading section-heading--split">
        <div><p className="kicker">Visueller Seitenblick</p><h2 id="artwork-impression-title">Eine Kunstspur.</h2></div>
        <p>Ein gemeinfreies Werk, assoziativ neben deine aktuelle Auswahl gestellt.</p>
      </div>
      <div className="artwork-impression__grid">
        <figure>
          <img src={artwork.image_url} alt={artwork.context ?? `${artwork.title} von ${artwork.artist_display}`} />
          <figcaption><a href={artwork.source_url} target="_blank" rel="noreferrer">{artwork.attribution} · {artwork.license} <IconExternalLink size={14} aria-hidden="true" /></a></figcaption>
        </figure>
        <div className="artwork-impression__copy">
          <p className="kicker">Art Institute of Chicago</p>
          <h3>{artwork.title}</h3>
          {facts.map((fact) => <p key={fact}>{fact}</p>)}
          {artwork.context ? <p className="artwork-impression__context">{artwork.context}</p> : null}
          {artwork.curation_reason ? <p className="curator-note">Warum hier: {artwork.curation_reason}</p> : null}
          <a className="artwork-impression__source" href={artwork.source_url} target="_blank" rel="noreferrer">Werk im Museum ansehen <IconExternalLink size={15} aria-hidden="true" /></a>
          <PreferenceFeedbackForm kind="artwork" targetId={artwork.id} />
        </div>
      </div>
    </section>
  );
}
