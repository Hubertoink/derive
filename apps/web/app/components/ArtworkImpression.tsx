"use client";

import { IconExternalLink, IconX } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { Artwork } from "../types";
import { PreferenceFeedbackForm } from "./PreferenceFeedbackForm";

export function ArtworkImpression({ artwork }: { artwork: Artwork }) {
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);
  const facts = [artwork.artist_display, artwork.date_display, artwork.medium_display, artwork.place_of_origin].filter(Boolean);
  const imageAlt = artwork.context ?? `${artwork.title} von ${artwork.artist_display}`;

  useEffect(() => {
    if (!isLightboxOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsLightboxOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [isLightboxOpen]);

  return (
    <>
      <section className="artwork-impression" aria-labelledby="artwork-impression-title">
        <div className="section-heading section-heading--split">
          <div><h2 id="artwork-impression-title">Eine Kunstspur.</h2></div>
          <p>Ein gemeinfreies Werk, assoziativ neben deine aktuelle Auswahl gestellt.</p>
        </div>
        <div className="artwork-impression__grid">
          <figure>
            <button className="artwork-impression__image-button" type="button" onClick={() => setIsLightboxOpen(true)} aria-label={`${artwork.title} in voller Größe anzeigen`}>
              <img src={artwork.image_url} alt={imageAlt} />
            </button>
            <figcaption><a href={artwork.source_url} target="_blank" rel="noreferrer">{artwork.attribution} · {artwork.license} <IconExternalLink size={14} aria-hidden="true" /></a></figcaption>
          </figure>
          <div className="artwork-impression__copy">
            <p className="kicker">{artwork.museum_name}</p>
            <h3>{artwork.title}</h3>
            {facts.map((fact) => <p key={fact}>{fact}</p>)}
            {artwork.context ? <p className="artwork-impression__context">{artwork.context}</p> : null}
            {artwork.curation_reason ? <p className="curator-note">Warum hier: {artwork.curation_reason}</p> : null}
            <a className="artwork-impression__source" href={artwork.source_url} target="_blank" rel="noreferrer">Werk im Museum ansehen <IconExternalLink size={15} aria-hidden="true" /></a>
            <PreferenceFeedbackForm kind="artwork" targetId={artwork.id} />
          </div>
        </div>
      </section>
      {isLightboxOpen ? (
        <div className="artwork-lightbox" role="dialog" aria-modal="true" aria-label={`${artwork.title} in voller Größe`} onMouseDown={() => setIsLightboxOpen(false)}>
          <button className="artwork-lightbox__close" type="button" onClick={() => setIsLightboxOpen(false)} aria-label="Großansicht schließen"><IconX aria-hidden="true" /></button>
          <div className="artwork-lightbox__content" onMouseDown={(event) => event.stopPropagation()}>
            <img src={artwork.image_url} alt={imageAlt} />
            <p>{artwork.title} · {artwork.artist_display}</p>
          </div>
        </div>
      ) : null}
    </>
  );
}
