"use client";

import { MouseEvent, useState } from "react";

export function SavePodcastButton({
  podcastId,
  initiallySaved,
  variant = "overview",
}: {
  podcastId: number;
  initiallySaved: boolean;
  variant?: "overview" | "reader";
}) {
  const [saved, setSaved] = useState(initiallySaved);
  const [busy, setBusy] = useState(false);

  async function toggle(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    const nextSaved = !saved;
    setSaved(nextSaved);
    setBusy(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/podcasts/${podcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ is_saved: nextSaved }),
      });
      if (!response.ok) setSaved(!nextSaved);
    } catch {
      setSaved(!nextSaved);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      className={variant === "overview" ? `overview-save${saved ? " is-saved" : ""}` : "podcast-save"}
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-label={saved ? "Podcast nicht mehr merken" : "Podcast merken"}
    >
      {saved ? "Gemerkt" : "Merken"}
    </button>
  );
}
