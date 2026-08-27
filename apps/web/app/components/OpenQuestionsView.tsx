"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";

import { answerReadingQuestion, generateReadingQuestions } from "../api";
import { ReadingProfile, ReadingQuestion } from "../types";

export function OpenQuestionsView({ initial }: { initial: ReadingQuestion[] }) {
  const [questions, setQuestions] = useState(initial);
  const [options, setOptions] = useState<Record<string, string | undefined>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [notice, setNotice] = useState("");
  const generationRequested = useRef(false);

  async function generate() {
    if (generating) return;
    setGenerating(true);
    setNotice("");
    try {
      const result = await generateReadingQuestions();
      setQuestions(result.profile.questions.filter((item) => item.status === "open"));
      setNotice(result.message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Neue Fragen konnten nicht geprüft werden.");
    } finally {
      setGenerating(false);
    }
  }

  useEffect(() => {
    if (initial.length || generationRequested.current) return;
    generationRequested.current = true;
    void generate();
    // The first automatic check is intentionally limited to one request per page load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>, question: ReadingQuestion) {
    event.preventDefault();
    if (busyKey) return;
    const option = options[question.key];
    const answer = answers[question.key]?.trim();
    if (!option && !answer) {
      setNotice("Wähle eine Antwort oder ergänze einen kurzen Gedanken.");
      return;
    }
    setBusyKey(question.key);
    setNotice("");
    try {
      const profile: ReadingProfile = await answerReadingQuestion(question.key, { status: "answered", option, answer: answer || undefined });
      setQuestions(profile.questions.filter((item) => item.status === "open"));
      setNotice("Danke. Deine Antwort wird ab jetzt als ausdrückliches Signal berücksichtigt.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Die Antwort konnte nicht gespeichert werden.");
    } finally {
      setBusyKey(null);
    }
  }

  async function skip(question: ReadingQuestion) {
    if (busyKey) return;
    setBusyKey(question.key);
    setNotice("");
    try {
      const profile = await answerReadingQuestion(question.key, { status: "skipped" });
      setQuestions(profile.questions.filter((item) => item.status === "open"));
      setNotice("Die Frage wurde übersprungen.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Die Frage konnte nicht übersprungen werden.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="open-questions-page">
      <section className="reading-profile-intro open-questions-intro">
        <div>
          <p className="kicker">Gemeinsam genauer werden</p>
          <h1>Offene Fragen.</h1>
        </div>
        <p>dérive fragt nur nach, wenn deine Antwort die nächsten Empfehlungen wirklich genauer machen kann. Du entscheidest, was bleibt.</p>
      </section>

      {questions.length ? (
        <section className="open-questions-list" aria-labelledby="open-questions-title">
          <div className="section-heading">
            <div><p className="kicker">Für dein Leseprofil</p><h2 id="open-questions-title">Ein paar Gedanken von dir.</h2></div>
            <p>Antworten werden als explizite Präferenzen gespeichert. Deine kuratorische Haltung bleibt unverändert.</p>
          </div>
          {questions.map((question) => {
            const selected = options[question.key];
            return (
              <form className="open-question-card" key={question.key} onSubmit={(event) => void submit(event, question)}>
                <div className="open-question-card__meta"><span>{question.kind === "format" ? "Leseform" : question.kind === "topic" ? "Thema" : question.kind === "perspective" ? "Perspektive" : question.kind === "source" ? "Quelle" : question.kind === "rhythm" ? "Rhythmus" : question.kind === "quality" ? "Qualität" : "Entdeckung"}{question.source === "ai" ? " · KI-formuliert" : ""}</span><small>{question.basis}</small></div>
                <h3>{question.question}</h3>
                <p>{question.context}</p>
                <div className="open-question-card__options" role="group" aria-label={question.question}>
                  {question.options.map((option) => (
                    <button type="button" key={option.value} className={selected === option.value ? "is-selected" : ""} aria-pressed={selected === option.value} onClick={() => setOptions((current) => ({ ...current, [question.key]: option.value }))}>{option.label}</button>
                  ))}
                </div>
                <label className="open-question-card__answer">
                  <span>Ein Gedanke dazu (optional)</span>
                  <textarea rows={3} value={answers[question.key] ?? ""} onChange={(event) => setAnswers((current) => ({ ...current, [question.key]: event.target.value }))} placeholder="Du kannst die Antwort gern in deinen eigenen Worten ergänzen …" />
                </label>
                <div className="open-question-card__actions">
                  <button className="button-primary" type="submit" disabled={busyKey !== null}>{busyKey === question.key ? "Wird bewahrt …" : "Antwort bewahren"}</button>
                  <button className="button-quiet" type="button" onClick={() => void skip(question)} disabled={busyKey !== null}>Überspringen</button>
                </div>
              </form>
            );
          })}
        </section>
      ) : (
        <section className="open-questions-empty">
          <p className="kicker">{generating ? "KI prüft dein Profil" : "Im Moment nichts offen"}</p>
          <h2>{generating ? "dérive sucht nach einer hilfreichen Rückfrage …" : "dérive lernt weiter aus deinem Lesefluss."}</h2>
          <p>{generating ? "Dabei werden nur vorhandene Lese- und Rückmeldesignale verwendet." : "Wenn ein Muster unklar wird oder eine Antwort deine Auswahl spürbar verbessern kann, erscheint hier eine neue Frage."}</p>
          <div>{!generating ? <button className="home-empty__primary" type="button" onClick={() => void generate()}>Neue Fragen prüfen</button> : null}<Link className="home-empty__secondary" href="/ki">Zum KI-Kurator</Link><Link className="home-empty__secondary" href="/leseprofil">Leseprofil ansehen</Link></div>
        </section>
      )}
      {notice ? <p className="open-questions-notice" role="status">{notice}</p> : null}
    </div>
  );
}
