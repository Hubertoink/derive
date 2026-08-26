"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { getArticleFeedback, saveArticleFeedback } from "../api";
import { ArticleFeedback, PreferenceReason } from "../types";

const ratings: { value: ArticleFeedback["rating"]; label: string }[] = [
  { value: "great", label: "Sehr" },
  { value: "yes", label: "Ja" },
  { value: "not_quite", label: "Nicht ganz" },
  { value: "no", label: "Nein" },
];
const reasons: { value: PreferenceReason; label: string }[] = [
  { value: "topic", label: "Thema" }, { value: "perspective", label: "Neue Perspektive" },
  { value: "depth", label: "Tiefe" }, { value: "style", label: "Stil" },
  { value: "source", label: "Quelle" }, { value: "too_shallow", label: "Zu oberflächlich" },
  { value: "too_familiar", label: "Zu vertraut" }, { value: "too_current", label: "Zu aktuell" },
];

export function ArticleFeedbackPrompt({ articleId, initiallyRead }: { articleId: number; initiallyRead: boolean }) {
  const [feedback, setFeedback] = useState<ArticleFeedback | null>(null);
  const [visible, setVisible] = useState(false);
  const [rating, setRating] = useState<ArticleFeedback["rating"] | null>(null);
  const [selectedReasons, setSelectedReasons] = useState<PreferenceReason[]>([]);
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
      const saved = await saveArticleFeedback(articleId, { rating, reasons: selectedReasons, note: note.trim() || undefined });
      setFeedback(saved);
      setVisible(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Die Rückmeldung konnte nicht gespeichert werden.");
    } finally {
      setBusy(false);
    }
  }

  if (feedback && !visible) {
    return <p className="reader-feedback__saved">Rückmeldung gespeichert · <button type="button" onClick={() => { setRating(feedback.rating); setSelectedReasons(feedback.reasons); setNote(feedback.note ?? ""); setVisible(true); }}>Ändern</button></p>;
  }
  if (!visible) return null;

  return (
    <form className="reader-feedback" onSubmit={submit}>
      <p className="kicker">Kurzer Rückblick</p>
      <p className="reader-feedback__question">Hat dir dieser Text etwas gegeben?</p>
      <div className="reader-feedback__ratings" role="group" aria-label="Artikel bewerten">
        {ratings.map((item) => <button key={item.value} type="button" aria-pressed={rating === item.value} className={rating === item.value ? "is-selected" : ""} onClick={() => setRating(item.value)}>{item.label}</button>)}
      </div>
      {rating ? <>
        <div className="preference-feedback__reasons">{reasons.map((reason) => <button key={reason.value} type="button" aria-pressed={selectedReasons.includes(reason.value)} className={selectedReasons.includes(reason.value) ? "is-selected" : ""} onClick={() => setSelectedReasons((current) => current.includes(reason.value) ? current.filter((item) => item !== reason.value) : [...current, reason.value])}>{reason.label}</button>)}</div>
        <label><span>Warum? (optional)</span><textarea rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Ein Satz genügt …" /></label>
        <button className="reader-feedback__save" type="submit" disabled={busy}>{busy ? "Wird gespeichert …" : "Rückmeldung speichern"}</button>
        {error ? <p className="reader-feedback__error" role="alert">{error}</p> : null}
      </> : null}
    </form>
  );
}
