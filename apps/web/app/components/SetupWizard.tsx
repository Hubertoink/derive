"use client";

import { KeyboardEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { saveSetup, testAI, testSpotify } from "../api";
import { AISetup, SetupStatus, SpotifySetup } from "../types";
import { BrandLogo } from "./BrandLogo";

const topics = [
  "Technologie", "Gesellschaft", "Politik", "Kultur", "Wissenschaft",
  "Wirtschaft", "Philosophie", "Musik", "Design", "Klima", "Literatur", "Geschichte",
];
const languages = ["Deutsch", "Englisch", "Französisch", "Spanisch", "Italienisch", "Niederländisch"];
const stepNames = ["Profil", "Interessen", "KI"];
const openAIModelSuggestions = ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4"];

function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function resolveTheme(theme: SetupStatus["theme"]): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: SetupStatus["theme"]): void {
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  window.dispatchEvent(new CustomEvent("reado-theme-change", { detail: resolved }));
}

export function SetupWizard({ initial, onboarding = false }: { initial: SetupStatus; onboarding?: boolean }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState(initial.display_name);
  const [theme, setTheme] = useState(initial.theme);
  const [preferredLanguages, setPreferredLanguages] = useState(initial.preferred_languages.length ? initial.preferred_languages : ["Deutsch", "Englisch"]);
  const [discoveryLanguages, setDiscoveryLanguages] = useState(initial.discovery_languages.length ? initial.discovery_languages : ["Deutsch", "Englisch"]);
  const [interests, setInterests] = useState(initial.interests);
  const [discoveryPrompt, setDiscoveryPrompt] = useState(initial.discovery_prompt);
  const [customInterest, setCustomInterest] = useState("");
  const [readingLength, setReadingLength] = useState(initial.reading_length);
  const [ai, setAI] = useState<AISetup>({ ...initial.ai, api_key: "" });
  const [pexelsApiKey, setPexelsApiKey] = useState("");
  const [spotify, setSpotify] = useState<SpotifySetup>({ ...initial.spotify, client_id: "", client_secret: "" });
  const [availableModels, setAvailableModels] = useState<string[]>(() => {
    const initialModel = initial.ai.model ? [initial.ai.model] : [];
    return initial.ai.provider === "openai"
      ? [...new Set([...initialModel, ...openAIModelSuggestions])]
      : initialModel;
  });
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Keep an explicit browser choice while the settings page is open. This
    // prevents a stale server default from switching an already light reader
    // back to dark before the user saves the form again.
    const stored = localStorage.getItem("reado-theme");
    const preferred = stored === "light" || stored === "dark" ? stored : initial.theme;
    setTheme(preferred);
    localStorage.setItem("reado-theme", preferred);
    applyTheme(preferred);
  }, [initial.theme]);

  function changeTheme(value: SetupStatus["theme"]) {
    setTheme(value);
    localStorage.setItem("reado-theme", value);
    applyTheme(value);
  }

  function addCustomInterest(event?: KeyboardEvent<HTMLInputElement>) {
    if (event && event.key !== "Enter") return;
    event?.preventDefault();
    const value = customInterest.trim();
    if (value && !interests.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setInterests((current) => [...current, value]);
    }
    setCustomInterest("");
  }

  function nextStep() {
    setNotice("");
    if (step === 1 && (!interests.length || !preferredLanguages.length || !discoveryLanguages.length)) {
      setNotice("Wähle mindestens ein Interesse und je eine Lese- und Entdeckungssprache.");
      return;
    }
    setStep((current) => Math.min(2, current + 1));
  }

  function selectProvider(provider: AISetup["provider"]) {
    if (provider === "openai") {
      setAvailableModels(openAIModelSuggestions);
      setAI({ provider, base_url: "https://api.openai.com/v1", model: openAIModelSuggestions[0], api_key: "", has_api_key: initial.ai.has_api_key });
    } else if (provider === "ollama") {
      setAvailableModels([]);
      setAI({ provider, base_url: "http://ollama:11434", model: "llama3.2", api_key: "", has_api_key: false });
    } else if (provider === "openai_compatible") {
      setAvailableModels([]);
      setAI({ provider, base_url: "", model: "", api_key: "", has_api_key: initial.ai.has_api_key });
    } else {
      setAvailableModels([]);
      setAI({ provider, base_url: null, model: null, api_key: "", has_api_key: false });
    }
    setNotice("");
  }

  async function checkAI() {
    setBusy(true);
    setNotice("");
    try {
      const result = await testAI(ai);
      setAvailableModels(result.models);
      if (result.models.length && !result.models.includes(ai.model ?? "")) {
        const selectedModel = result.models[0];
        setAI((current) => ({ ...current, model: selectedModel }));
        setNotice(`${result.message} Vorausgewählt: ${selectedModel}.`);
      } else {
        setNotice(result.message);
      }
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function checkSpotify() {
    setBusy(true);
    setNotice("");
    try {
      const result = await testSpotify(spotify);
      setNotice(result.message);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (ai.provider !== "disabled" && (!ai.base_url?.trim() || !ai.model?.trim())) {
      setNotice("Trage für die KI eine Basis-URL und ein Modell ein.");
      return;
    }
    if (ai.provider === "openai" && !ai.api_key && !ai.has_api_key) {
      setNotice("Trage deinen OpenAI API-Schlüssel ein oder deaktiviere die KI zunächst.");
      return;
    }
    setBusy(true);
    setNotice("dérive richtet deinen KI-kuratierten Leseraum ein …");
    try {
      const result = await saveSetup({
        display_name: displayName,
        preferred_languages: preferredLanguages,
        discovery_languages: discoveryLanguages,
        interests,
        discovery_prompt: discoveryPrompt,
        reading_length: readingLength,
        theme,
        ai: { provider: ai.provider, base_url: ai.base_url, model: ai.model, api_key: ai.api_key },
        pexels_api_key: pexelsApiKey,
        spotify: { client_id: spotify.client_id, client_secret: spotify.client_secret },
      });
      setTheme(result.theme);
      localStorage.setItem("reado-theme", result.theme);
      applyTheme(result.theme);
      setNotice("Gespeichert. Deine KI-Kuration ist eingerichtet.");
      if (onboarding) router.refresh();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={`setup-shell${onboarding ? " setup-shell--onboarding" : ""}`}>
      <header className="setup-header">
        <div className="setup-header__start">
          <BrandLogo linked={!onboarding} />
          {!onboarding ? <Link className="setup-back-link" href="/">← Zurück zum Leseraum</Link> : null}
        </div>
        <span>{onboarding ? "Ersteinrichtung" : "Einstellungen"}</span>
      </header>
      <div className="setup-layout">
        <aside className="setup-progress" aria-label="Einrichtungsschritte">
          <ol>{stepNames.map((name, index) => <li key={name} className={index === step ? "is-current" : index < step ? "is-done" : ""}><button type="button" onClick={() => setStep(index)}><span>0{index + 1}</span>{name}</button></li>)}</ol>
          <p>Deine Einstellungen bleiben in deiner dérive-Instanz. API-Schlüssel werden verschlüsselt gespeichert.</p>
        </aside>
        <section className="setup-card" aria-live="polite">
          {step === 0 ? <>
            <p className="kicker">Willkommen bei dérive</p>
            <h1>Richten wir deinen Leseraum ein.</h1>
            <p className="setup-lead">Vier kurze Schritte, danach beginnt dérive mit deinen eigenen Quellen statt mit einer leeren Oberfläche.</p>
            <div className="setup-fields two-columns">
              <label><span>Wie dürfen wir dich nennen?</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Optional" autoFocus /></label>
              <label><span>Darstellung</span><select value={theme} onChange={(event) => changeTheme(event.target.value as SetupStatus["theme"])}><option value="system">Systemeinstellung</option><option value="light">Hell</option><option value="dark">Dunkel</option></select></label>
            </div>
          </> : null}

          {step === 1 ? <>
            <p className="kicker">Geschmack statt Algorithmus</p>
            <h1>Was möchtest du häufiger lesen?</h1>
            <p className="setup-lead">Das ist ein Ausgangspunkt. dérive verfeinert die Auswahl später anhand deines tatsächlichen Leseverhaltens.</p>
            <fieldset><legend>Interessen</legend><div className="choice-grid">{topics.map((topic) => <button type="button" key={topic} className={interests.includes(topic) ? "is-selected" : ""} onClick={() => setInterests(toggle(interests, topic))}>{topic}</button>)}</div></fieldset>
            <div className="inline-entry"><input value={customInterest} onChange={(event) => setCustomInterest(event.target.value)} onKeyDown={addCustomInterest} placeholder="Eigenes Interesse, z. B. europäische Technologiepolitik" /><button type="button" onClick={() => addCustomInterest()}>Hinzufügen</button></div>
            {interests.some((interest) => !topics.includes(interest)) ? <div className="selected-custom">{interests.filter((interest) => !topics.includes(interest)).map((interest) => <button type="button" key={interest} onClick={() => setInterests(toggle(interests, interest))}>{interest} ×</button>)}</div> : null}
            <div className="setup-fields two-columns compact-fields">
              <fieldset><legend>Bevorzugte Lesesprachen</legend><div className="check-list">{languages.map((language) => <label key={language}><input type="checkbox" checked={preferredLanguages.includes(language)} onChange={() => setPreferredLanguages(toggle(preferredLanguages, language))} /> {language}</label>)}</div></fieldset>
              <fieldset><legend>Entdeckungssprachen</legend><div className="check-list">{languages.map((language) => <label key={language}><input type="checkbox" checked={discoveryLanguages.includes(language)} onChange={() => setDiscoveryLanguages(toggle(discoveryLanguages, language))} /> {language}</label>)}</div></fieldset>
            </div>
            <label className="full-field"><span>Bevorzugte Textlänge</span><select value={readingLength} onChange={(event) => setReadingLength(event.target.value as SetupStatus["reading_length"])}><option value="mixed">Gemischt</option><option value="short">Kurz · bis 5 Minuten</option><option value="medium">Mittel · 5–15 Minuten</option><option value="long">Lang · ab 15 Minuten</option></select></label>
          </> : null}

          {step === 1 ? <label className="full-field setup-profile-prompt"><span>Was soll die KI bei der Auswahl beachten?</span><textarea rows={4} value={discoveryPrompt} onChange={(event) => setDiscoveryPrompt(event.target.value)} placeholder="Zum Beispiel: erzählerische Reportagen, sorgfältige Recherche, wenig Tagespolitik, gern Europa und USA …" /></label> : null}

          {step === 2 ? <>
            <p className="kicker">Optionale Intelligenz</p>
            <h1>Wie soll dérive KI verwenden?</h1>
            <p className="setup-lead">Die KI sucht auf Wunsch nach passenden Longform-Texten. Webfunde verlinken immer zur Originalquelle.</p>
            <label className="full-field"><span>Provider</span><select value={ai.provider} onChange={(event) => selectProvider(event.target.value as AISetup["provider"])}><option value="disabled">Zunächst ohne KI</option><option value="ollama">Ollama · lokal</option><option value="openai">OpenAI API</option><option value="openai_compatible">OpenAI-kompatible API</option></select></label>
            {ai.provider !== "disabled" ? <div className="setup-fields two-columns ai-fields">
              <label><span>API-Basis-URL</span><input type="url" value={ai.base_url ?? ""} onChange={(event) => setAI({ ...ai, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label>
              <label><span>Modell</span>{availableModels.length ? <select value={ai.model ?? ""} onChange={(event) => setAI({ ...ai, model: event.target.value })}>{availableModels.map((model) => <option key={model} value={model}>{model}</option>)}</select> : <input value={ai.model ?? ""} onChange={(event) => setAI({ ...ai, model: event.target.value })} placeholder="Erst Verbindung testen oder Modell-ID eingeben" />}</label>
              {ai.provider !== "ollama" ? <label className="api-key-field"><span>API-Schlüssel</span><input type="password" autoComplete="off" value={ai.api_key ?? ""} onChange={(event) => setAI({ ...ai, api_key: event.target.value })} placeholder={ai.has_api_key ? "Gespeicherten Schlüssel beibehalten" : "sk-…"} /><small>Wird verschlüsselt gespeichert und nie wieder angezeigt.</small></label> : null}
              <div className="ai-test"><button type="button" onClick={checkAI} disabled={busy}>{busy ? "Modelle werden geladen …" : "Verbindung testen & Modelle laden"}</button></div>
            </div> : <div className="ai-disabled-note"><strong>Kein Problem.</strong><p>Du kannst die KI-Verbindung später ergänzen.</p></div>}
            <label className="full-field pexels-key-field"><span>Pexels API-Schlüssel (optional)</span><input type="password" autoComplete="off" value={pexelsApiKey} onChange={(event) => setPexelsApiKey(event.target.value)} placeholder={initial.pexels.has_api_key ? "Gespeicherten Pexels-Schlüssel beibehalten" : "Pexels-Schlüssel für wechselnde Titelbilder"} /><small>Wird verschlüsselt gespeichert. Ohne eigenen Schlüssel bleibt ein vorhandener Umgebungs-Schlüssel aktiv.</small></label>
            <fieldset className="spotify-fields"><legend>Spotify Podcast-Suche (optional)</legend><p>Ergänzt die KI-Suche um direkte Episoden aus dem Spotify-Katalog. Spotify-Metadaten werden nicht an die KI gesendet.</p><div className="setup-fields two-columns"><label><span>Client ID</span><input type="password" autoComplete="off" value={spotify.client_id ?? ""} onChange={(event) => setSpotify({ ...spotify, client_id: event.target.value })} placeholder={initial.spotify.has_client_id ? "Gespeicherte Client ID beibehalten" : "Spotify Client ID"} /></label><label><span>Client Secret</span><input type="password" autoComplete="off" value={spotify.client_secret ?? ""} onChange={(event) => setSpotify({ ...spotify, client_secret: event.target.value })} placeholder={initial.spotify.has_client_secret ? "Gespeichertes Client Secret beibehalten" : "Spotify Client Secret"} /></label></div><div className="ai-test"><button type="button" onClick={checkSpotify} disabled={busy}>{busy ? "Spotify wird geprüft …" : "Spotify-Verbindung testen"}</button></div><small>Wird verschlüsselt gespeichert. Kein Spotify-Login und keine Redirect-URL nötig.</small></fieldset>
          </> : null}

          {notice ? <p className="setup-notice" role="status">{notice}</p> : null}
          <footer className="setup-footer">
            <button type="button" className="button-quiet" onClick={() => setStep((current) => Math.max(0, current - 1))} disabled={step === 0 || busy}>Zurück</button>
            <span>Schritt {step + 1} von {stepNames.length}</span>
            {step < 2 ? <button type="button" className="button-primary" onClick={nextStep}>Weiter</button> : <button type="button" className="button-primary" onClick={finish} disabled={busy}>{busy ? "Wird gespeichert …" : onboarding ? "dérive starten" : "Einstellungen speichern"}</button>}
          </footer>
        </section>
      </div>
    </main>
  );
}
