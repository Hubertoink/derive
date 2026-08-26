"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { BrandLogo } from "../components/BrandLogo";

export default function LoginPage() {
  const [next, setNext] = useState("/");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setNext(new URLSearchParams(window.location.search).get("next") || "/"); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier, password, next }) });
      if (!response.ok) { const body = await response.json().catch(() => ({})) as { detail?: string }; throw new Error(body.detail || "Anmeldung nicht möglich."); }
      const body = await response.json() as { next?: string }; window.location.assign(body.next || "/");
    } catch (reason) { setError((reason as Error).message); setBusy(false); }
  }
  return <main className="login-page"><div className="login-modal" role="dialog" aria-labelledby="login-title">
    <BrandLogo linked={false} />
    <p className="kicker">Privater Leseraum</p><h1 id="login-title">Willkommen bei dérive.</h1>
    <p className="login-lead">Melde dich an, um deinen persönlichen Leseraum zu öffnen.</p>
    <form onSubmit={submit}>
      <label><span>Benutzername oder E-Mail</span><input autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} required /></label>
      <label><span>Passwort</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error ? <p className="login-error" role="alert">{error}</p> : null}
      <button className="button-primary" type="submit" disabled={busy}>{busy ? "Wird geöffnet …" : "Leseraum öffnen"}</button>
    </form>
    <p className="login-alternate">Du hast eine Einladung? <Link href="/registrieren">Konto anlegen</Link></p>
  </div></main>;
}
