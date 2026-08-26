"use client";

import { useEffect, useState } from "react";

export function ReaderActions({
  articleId,
  initiallySaved,
  initiallyRead,
}: {
  articleId: number;
  initiallySaved: boolean;
  initiallyRead: boolean;
}) {
  const [isSaved, setIsSaved] = useState(initiallySaved);
  const [isRead, setIsRead] = useState(initiallyRead);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function updateState(update: { is_saved?: boolean; is_read?: boolean }) {
    if (busy) return;
    const previousSaved = isSaved;
    const previousRead = isRead;
    if (update.is_saved !== undefined) setIsSaved(update.is_saved);
    if (update.is_read) setIsRead(true);
    setBusy(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/articles/${articleId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(update),
      });
      if (!response.ok) throw new Error("save failed");
    } catch {
      setIsSaved(previousSaved);
      setIsRead(previousRead);
      setNotice("Die Änderung konnte nicht gespeichert werden.");
      return;
    } finally {
      setBusy(false);
    }
    setNotice(update.is_read ? "Als gelesen markiert." : "Gespeichert.");
  }

  useEffect(() => {
    const markRead = (event: Event) => {
      if ((event as CustomEvent<number>).detail === articleId) setIsRead(true);
    };
    window.addEventListener("reado:article-read", markRead);
    return () => window.removeEventListener("reado:article-read", markRead);
  }, [articleId]);

  return (
    <div className="reader-actions">
      <button type="button" onClick={() => updateState({ is_saved: !isSaved })} disabled={busy}>
        {isSaved ? "Nicht mehr merken" : "Merken"}
      </button>
      <button type="button" onClick={() => updateState({ is_read: true })} disabled={isRead || busy}>
        {isRead ? "Als gelesen markiert" : "Als gelesen markieren"}
      </button>
      <span className="sr-only" role="status">
        {notice}
      </span>
    </div>
  );
}

