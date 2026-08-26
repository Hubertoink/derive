"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { getArticleFeedback, saveArticleFeedback } from "../api";
import { ArticleFeedback } from "../types";

const ratings: { value: ArticleFeedback["rating"]; label: string }[] = [
  { value: "great", label: "Sehr" },
  { value: "yes", label: "Ja" },
  { value: "not_quite", label: "Nicht ganz" },
  { value: "no", label: "Nein" },
];

export function ArticleFeedbackPrompt({ articleId, initiallyRead }: { articleId: number; initiallyRead: boolean }) {
  const [feedback, setFeedback] = useState<ArticleFeedback | null>(null);
  const [visible, setVisible] = useState(false);
  const [rating, setRating] = useState<ArticleFeedback["rating"] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const feedbackRef = useRef<ArticleFeedback | null>(null);

  useEffect(() => {
    let active = true;
    void getArticleFeedback(articleId).then((value) => {
      if (active) {
        feedbackRef.current = value;
        setFeedback(value);
      }
    }).catch(() => undefined);
    const reveal = () => {
      if (active && !feedbackRef.current) setVisible(true);
    };
    const timer = window.setTimeout(reveal, initiallyRead ? 7000 : 15000);
    const onRead = (event: Event) => {
      if ((event as CustomEvent<number>).detail === articleId) window.setTimeout(reveal, 7000);
    };
    window.addEventListener("reado:article-read", onRead);
    return () => {
      active = false;
      window.clearTimeout(timer);
      window.removeEventListener("reado:article-read", onRead);
    };
  }, [articleId, initiallyRead]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!rating || busy) return;
    setBusy(true);
    setError("");
    try {
      const saved = await saveArticleFeedback(articleId, { rating, note: note.trim() || undefined });
      setFeedback(saved);
      setVisible(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Die Rückmeldung konnte nicht gespeichert werden.");
    } finally {
      setBusy(false);
    }
  }

  if (feedback && !visible) {
    return <p className="reader-feedback__saved">Rückmeldung gespeichert · <button type="button" onClick={() => { setRating(feedback.rating); setNote(feedback.note ?? ""); setVisible(true); }}>Ändern</button></p>;
  }
  if (!visible) return null;

  return (
    <form className="reader-feedback" onSubmit={submit}>
      <p className="kicker">Kurzer Rückblick</p>
      <p className="reader-feedback__question">Hat dir dieser Text etwas gegeben?</p>
      <div className="reader-feedback__ratings" role="group" aria-label="Artikel bewerten">
        {ratings.map((item) => <button key={item.value} type="button" className={rating === item.value ? "is-selected" : ""} onClick={() => setRating(item.value)}>{item.label}</button>)}
      </div>
      {rating ? <>
        <label><span>Warum? (optional)</span><textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Ein Satz genügt …" /></label>
        <button className="reader-feedback__save" type="submit" disabled={busy}>{busy ? "Wird gespeichert …" : "Rückmeldung speichern"}</button>
        {error ? <p className="reader-feedback__error" role="alert">{error}</p> : null}
      </> : null}
    </form>
  );
}
