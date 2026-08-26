"use client";

import { FormEvent, useEffect, useState } from "react";

type Account = { id: number; username: string; email: string; role: string; is_active: boolean };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

export function AccountPanel() {
  const [account, setAccount] = useState<Account | null>(null);
  const [users, setUsers] = useState<Account[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    void fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<{ user: Account }> : null)
      .then((payload) => {
        if (!payload) return;
        setAccount(payload.user);
        if (payload.user.role === "admin") {
          return fetch(`${apiUrl}/api/v1/admin/users`, { credentials: "include" })
            .then(async (response) => response.ok ? response.json() as Promise<{ users: Account[] }> : null)
            .then((result) => setUsers(result?.users ?? []));
        }
      })
      .catch(() => setNotice("Konto konnte nicht geladen werden."));
  }, []);

  async function createInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setNotice(""); setInviteLink("");
    const response = await fetch(`${apiUrl}/api/v1/admin/invitations`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: inviteEmail.trim() || null }),
    });
    const payload = await response.json().catch(() => ({})) as { detail?: string; invitation?: { url: string } };
    if (!response.ok) { setNotice(payload.detail ?? "Einladung konnte nicht angelegt werden."); return; }
    setInviteEmail(""); setInviteLink(`${window.location.origin}${payload.invitation?.url ?? ""}`);
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.assign("/login");
  }

  async function toggleUser(user: Account) {
    const response = await fetch(`${apiUrl}/api/v1/admin/users/${user.id}`, {
      method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !user.is_active }),
    });
    const payload = await response.json().catch(() => ({})) as { detail?: string; user?: Account };
    if (!response.ok || !payload.user) { setNotice(payload.detail ?? "Kontostatus konnte nicht geändert werden."); return; }
    setUsers((current) => current.map((item) => item.id === user.id ? payload.user as Account : item));
  }

  if (!account) return <p className="account-notice">Konto wird geladen …</p>;
  return <section className="account-panel">
    <div className="account-panel__identity"><p className="kicker">Dein Konto</p><h2>{account.username}</h2><p>{account.email} · {account.role === "admin" ? "Administration" : "Mitglied"}</p></div>
    <button type="button" className="account-panel__logout" onClick={() => void logout()}>Abmelden</button>
    {account.role === "admin" ? <section className="account-admin"><p className="kicker">Einladungen</p><h3>Weitere Lesräume eröffnen</h3><p>Einladungen sind einmalig und laufen nach 48 Stunden ab. Ohne Einladung kann niemand ein Konto anlegen.</p>
      <form onSubmit={createInvitation}><input type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="E-Mail optional" /><button type="submit">Einladung erzeugen</button></form>
      {inviteLink ? <p className="account-invite"><span>Einladungslink</span><input readOnly value={inviteLink} onFocus={(event) => event.currentTarget.select()} /></p> : null}
      {users.length ? <ul className="account-users">{users.map((user) => <li key={user.id}><strong>{user.username}</strong><span>{user.email}</span><small>{user.role === "admin" ? "Administration" : user.is_active ? "Aktiv" : "Deaktiviert"}</small>{user.id !== account.id ? <button type="button" onClick={() => void toggleUser(user)}>{user.is_active ? "Deaktivieren" : "Aktivieren"}</button> : null}</li>)}</ul> : null}
    </section> : null}
    {notice ? <p className="account-notice">{notice}</p> : null}
  </section>;
}
