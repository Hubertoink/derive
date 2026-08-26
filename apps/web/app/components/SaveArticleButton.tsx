"use client";

import { MouseEvent, useState } from "react";

export function SaveArticleButton({ articleId, initiallySaved }: { articleId: number; initiallySaved: boolean }) {
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
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/articles/${articleId}`, {
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

  return <button className={`overview-save${saved ? " is-saved" : ""}`} type="button" onClick={toggle} disabled={busy} aria-label={saved ? "Nicht mehr merken" : "Artikel merken"} title={saved ? "Nicht mehr merken" : "Merken"}>{saved ? "Gemerkt" : "Merken"}</button>;
}
