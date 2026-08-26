"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { BrandLogo } from "../components/BrandLogo";

export default function RegisterPage() {
  const [invitationToken, setInvitationToken] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => setInvitationToken(new URLSearchParams(window.location.search).get("invite") ?? ""), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, password, invitation_token: invitationToken }),
      });
      const body = await response.json().catch(() => ({})) as { detail?: string };
      if (!response.ok) throw new Error(body.detail ?? "Das Konto konnte nicht angelegt werden.");
      window.location.assign("/");
    } catch (reason) {
      setError((reason as Error).message); setBusy(false);
    }
  }

  return <main className="login-page"><div className="login-modal" role="dialog" aria-labelledby="register-title">
    <BrandLogo linked={false} />
    <p className="kicker">Dein Zugang</p><h1 id="register-title">Willkommen bei dérive.</h1>
    <p className="login-lead">Lege mit deiner persönlichen Einladung einen eigenen, privaten Leseraum an.</p>
    <form onSubmit={submit}>
      <label><span>Einladungscode</span><input value={invitationToken} onChange={(event) => setInvitationToken(event.target.value)} required /></label>
      <label><span>Benutzername</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
      <label><span>E-Mail</span><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
      <label><span>Passwort</span><input type="password" minLength={12} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error ? <p className="login-error" role="alert">{error}</p> : null}
      <button className="button-primary" type="submit" disabled={busy}>{busy ? "Wird angelegt …" : "Leseraum anlegen"}</button>
    </form>
    <p className="login-alternate">Schon ein Konto? <Link href="/login">Anmelden</Link></p>
  </div></main>;
}
