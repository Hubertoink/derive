"use client";

import { FormEvent, useEffect, useState } from "react";

import { getArtworkFeedback, getPodcastFeedback, saveArtworkFeedback, savePodcastFeedback } from "../api";
import { ArticleFeedback, PreferenceReason } from "../types";

const ratings: { value: ArticleFeedback["rating"]; label: string }[] = [
  { value: "great", label: "Sehr" }, { value: "yes", label: "Ja" },
  { value: "not_quite", label: "Nicht ganz" }, { value: "no", label: "Nein" },
];
const reasons: { value: PreferenceReason; label: string }[] = [
  { value: "topic", label: "Thema" }, { value: "perspective", label: "Neue Perspektive" },
  { value: "depth", label: "Tiefe" }, { value: "style", label: "Stil" },
  { value: "source", label: "Quelle" }, { value: "too_shallow", label: "Zu oberflächlich" },
  { value: "too_familiar", label: "Zu vertraut" }, { value: "too_current", label: "Zu aktuell" },
];

export function PreferenceFeedbackForm({ kind, targetId }: { kind: "podcast" | "artwork"; targetId: number }) {
  const [rating, setRating] = useState<ArticleFeedback["rating"] | null>(null);
  const [selectedReasons, setSelectedReasons] = useState<PreferenceReason[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    const request = kind === "podcast" ? getPodcastFeedback(targetId) : getArtworkFeedback(targetId);
    void request.then((feedback) => {
      if (!active || !feedback) return;
      setRating(feedback.rating);
      setSelectedReasons(feedback.reasons);
      setNote(feedback.note ?? "");
      setNotice("Deine bisherige Rückmeldung ist geladen und kann geändert werden.");
    }).catch(() => undefined);
    return () => { active = false; };
  }, [kind, targetId]);

  function toggle(reason: PreferenceReason) {
    setSelectedReasons((current) => current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!rating || busy) return;
    setBusy(true);
    setNotice("");
    try {
      const payload = { rating, reasons: selectedReasons, note: note.trim() || undefined };
      if (kind === "podcast") await savePodcastFeedback(targetId, payload);
      else await saveArtworkFeedback(targetId, payload);
      setNotice("Rückmeldung gespeichert. Sie fließt als ausdrückliches Signal in die nächste Auswahl ein.");
    } catch (error) {
      setNotice((error as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <form className={`preference-feedback preference-feedback--${kind}`} onSubmit={(event) => void submit(event)}>
      <p>{kind === "podcast" ? "Passte diese Episode zu dir?" : "War dieser visuelle Seitenblick stimmig?"}</p>
      <div className="reader-feedback__ratings" role="group" aria-label="Passung bewerten">
        {ratings.map((item) => <button key={item.value} type="button" aria-pressed={rating === item.value} className={rating === item.value ? "is-selected" : ""} onClick={() => setRating(item.value)}>{item.label}</button>)}
      </div>
      {rating ? <><div className="preference-feedback__reasons">{reasons.map((reason) => <button key={reason.value} type="button" aria-pressed={selectedReasons.includes(reason.value)} className={selectedReasons.includes(reason.value) ? "is-selected" : ""} onClick={() => toggle(reason.value)}>{reason.label}</button>)}</div><label><span>Ein Gedanke dazu (optional)</span><textarea rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Was passte – oder was fehlte?" /></label><button className="reader-feedback__save" type="submit" disabled={busy}>{busy ? "Wird gespeichert …" : "Eindruck bewahren"}</button></> : null}
      {notice ? <small role="status">{notice}</small> : null}
    </form>
  );
}
