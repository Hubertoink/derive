"use client";

import { FormEvent, useState } from "react";

import { saveArticleFeedback } from "../api";
import { Article, ArticleFeedback } from "../types";

const ratings: { value: ArticleFeedback["rating"]; label: string }[] = [
  { value: "great", label: "Sehr" },
  { value: "yes", label: "Ja" },
  { value: "not_quite", label: "Nicht ganz" },
  { value: "no", label: "Nein" },
];

export function ReflectionQuestions({ initial }: { initial: Article[] }) {
  const [articles, setArticles] = useState(initial);
  const [ratingsByArticle, setRatingsByArticle] = useState<Record<number, ArticleFeedback["rating"] | undefined>>({});
  const [notesByArticle, setNotesByArticle] = useState<Record<number, string | undefined>>({});
  const [busyArticleId, setBusyArticleId] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>, articleId: number) {
    event.preventDefault();
    const rating = ratingsByArticle[articleId];
    if (!rating || busyArticleId !== null) return;

    setBusyArticleId(articleId);
    setError("");
    try {
      await saveArticleFeedback(articleId, { rating, note: notesByArticle[articleId]?.trim() || undefined });
      setArticles((current) => current.filter((article) => article.id !== articleId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Die Rückmeldung konnte nicht gespeichert werden.");
    } finally {
      setBusyArticleId(null);
    }
  }

  if (!articles.length) return null;

  return (
    <section className="reflection-questions" aria-labelledby="reflection-questions-title">
      <div className="section-heading section-heading--split">
        <div>
          <p className="kicker">Zwischen den Texten</p>
          <h2 id="reflection-questions-title">Was blieb bei dir?</h2>
        </div>
        <p>Ein kurzer Eindruck hilft dérive, die nächste Auswahl leiser und genauer auf dich abzustimmen.</p>
      </div>
      <div className="reflection-questions__list">
        {articles.map((article) => {
          const rating = ratingsByArticle[article.id];
          return (
            <form key={article.id} onSubmit={(event) => void submit(event, article.id)}>
              <p className="article-row__eyebrow">{article.source} · {article.reading_minutes} Min. Lesezeit</p>
              <h3>{article.title}</h3>
              <p className="reflection-questions__prompt">Hat dieser Text noch etwas bei dir in Bewegung gebracht?</p>
              <div className="reader-feedback__ratings" role="group" aria-label={`${article.title} bewerten`}>
                {ratings.map((item) => (
                  <button key={item.value} type="button" className={rating === item.value ? "is-selected" : ""} onClick={() => setRatingsByArticle((current) => ({ ...current, [article.id]: item.value }))}>{item.label}</button>
                ))}
              </div>
              {rating ? (
                <label className="reflection-questions__note">
                  <span>Ein Gedanke dazu (optional)</span>
                  <textarea rows={2} value={notesByArticle[article.id] ?? ""} onChange={(event) => setNotesByArticle((current) => ({ ...current, [article.id]: event.target.value }))} placeholder="Was passte – oder was fehlte?" />
                  <button className="reader-feedback__save" type="submit" disabled={busyArticleId !== null}>{busyArticleId === article.id ? "Wird gespeichert …" : "Eindruck bewahren"}</button>
                </label>
              ) : null}
            </form>
          );
        })}
      </div>
      {error ? <p className="reader-feedback__error" role="alert">{error}</p> : null}
    </section>
  );
}
