# dérive

dérive ist ein ruhiger, persönlicher Leseraum für lange Texte, Podcasts und
transparent kuratierte Entdeckungen. Originalquellen bleiben zentral; bei
Paywalls zeigt dérive den Hinweis und den Link, statt Zugänge zu umgehen.

## Funktionen

- Persönliche Startseite für lange Reportagen, Essays und Podcasts
- KI-Kuration über die OpenAI-Websuche mit Einordnung und Original-Link
- Automatischer Suchrhythmus über einen separaten Worker
- Quellen-Memory: passende Publikationen werden pro Konto gelernt und rotierend genutzt
- Offene Suche bleibt Teil jedes Laufs, damit der Quellenpool nicht zur Filterblase wird
- Manuelle Quellenregeln mit **Bevorzugen**, **Seltener** und **Ausschließen**
- Lokaler Chat-Kurator, Leseprofil, Feedback und Merkliste
- Geschlossener Mehrbenutzerbetrieb mit Einladungen

## Architektur

| Dienst | Aufgabe |
| --- | --- |
| `web` | Next.js-Oberfläche und Proxy für die API |
| `api` | FastAPI, Authentifizierung, Kuration und Datenzugriff |
| `worker` | Prüft den Zeitplan jede Minute und führt automatische Suchen aus |
| `postgres` | Dauerhafte Datenbank für Konten, Artikel, Feedback und Quellen-Memory |

Der Worker muss dauerhaft laufen, wenn automatische Suchen gewünscht sind.
Beim Start holt er einen überfälligen Lauf nach. Die Quellen-Memory wird beim
ersten Start aus bereits gespeicherten KI-Empfehlungen aufgebaut.

## Lokaler Start

Voraussetzung sind Docker Desktop mit Docker Compose sowie ein erreichbarer
OpenAI API-Schlüssel für die Websuche.

1. Kopiere `.env.example` nach `.env`.
2. Setze Datenbankpasswort, `READO_SECRET_KEY` und einmalig die drei
   Bootstrap-Variablen:

   ```env
   DERIVE_BOOTSTRAP_ADMIN_USERNAME=dein-name
   DERIVE_BOOTSTRAP_ADMIN_EMAIL=du@example.org
   DERIVE_BOOTSTRAP_ADMIN_PASSWORD=ein-langes-eigenes-passwort
   ```

3. Starte den Stack:

   ```bash
   docker compose up --build
   ```

4. Öffne <http://localhost:3001> und melde dich mit diesem Konto an.

Beim ersten Start werden Datenbanktabellen und das Administrationskonto
automatisch angelegt. Nach Änderungen am Code kann der Stack mit folgendem
Befehl neu gebaut werden:

```bash
docker compose up -d --build
```

Die Datenbank liegt in einem Docker-Volume und bleibt bei Container-Neustarts
erhalten. Das Volume sollte regelmäßig mit den üblichen PostgreSQL-Werkzeugen
gesichert werden.

## Konten und Datenschutz

dérive ist standardmäßig ein geschlossener Mehrbenutzer-Leseraum. Die drei
`DERIVE_BOOTSTRAP_ADMIN_*`-Variablen erzeugen beim allerersten Start genau ein
Administrationskonto. Anschließend werden diese Werte nie mehr zur Anmeldung
ausgelesen. Der Admin erstellt im Bereich **Konto** einmalige
Einladungslinks; darüber richten weitere Menschen ihren eigenen Leseraum ein.

Passwörter werden als Argon2-Hash gespeichert. Der Browser enthält nur ein
zufälliges, HttpOnly-Sitzungs-Cookie; dessen Hash liegt serverseitig und kann
bei Abmeldung oder Kontosperrung widerrufen werden. Der Inhaltskatalog kann
gemeinsam sein, aber Lesestatus, Merkliste, Feedback, Leseprofil,
Kurator-Chat, KI-Einstellungen, Feeds und persönliche Volltext-Importe sind
pro Konto getrennt. Beim Upgrade ordnet dérive bestehende Einzelnutzerdaten
automatisch dem ersten Admin zu.

| Variable | Zweck |
| --- | --- |
| `DERIVE_BOOTSTRAP_ADMIN_USERNAME` | Benutzername des ersten Administrators; nur beim ersten Start verwendet. |
| `DERIVE_BOOTSTRAP_ADMIN_EMAIL` | E-Mail des ersten Administrators; nur beim ersten Start verwendet. |
| `DERIVE_BOOTSTRAP_ADMIN_PASSWORD` | Passwort des ersten Administrators (mindestens 12 Zeichen); nur beim ersten Start verwendet. |
| `DERIVE_ALLOW_PUBLIC_SIGNUP` | Öffnet die Registrierung bewusst für alle (`false` ist der sichere Standard). |
| `DERIVE_SESSION_TTL_DAYS` | Laufzeit einer Sitzung, von 1 bis 31 Tagen (Standard: 14). |
| `DERIVE_INVITE_LIFETIME_HOURS` | Laufzeit eines Einladungslinks (Standard: 48 Stunden). |
| `DERIVE_AUTH_SECURE_COOKIE` | Auf `true` setzen, wenn dérive hinter HTTPS läuft. |
| `READO_SECRET_KEY` | Stabiler, langer Schlüssel zum Verschlüsseln der KI- und FreshRSS-Zugangsdaten in der Datenbank. |

Die frühere `DERIVE_AUTH_*`-Konfiguration wird nur noch als einmaliger
Kompatibilitäts-Fallback für den ersten Admin akzeptiert. Sie sollte durch die
Bootstrap-Variablen ersetzt werden.

## ZimaOS

`compose.zimaos.yaml` ist für ZimaOS vorbereitet. Lade den vollständigen
Projektordner mit `apps/api` und `apps/web` hoch, setze die Variablen in der
ZimaOS-Compose-Oberfläche und starte ihn dort. Per SSH geht es auch so:

```bash
docker compose -f compose.zimaos.yaml up -d --build
```

Für den ersten Test sind Benutzername `Hubertoink` und E-Mail
`hubertoink@outlook.com` voreingestellt. Ersetze unbedingt
`DERIVE_BOOTSTRAP_ADMIN_PASSWORD`, `POSTGRES_PASSWORD` und
`READO_SECRET_KEY` durch eigene, lange Werte. Für eine öffentliche Domain
setze `DERIVE_AUTH_SECURE_COOKIE=true` und stelle HTTPS über den ZimaOS-Proxy
oder einen Reverse Proxy bereit. Die API bleibt dabei im Docker-Netz; der
Browser spricht über den Web-Container mit ihr.

## KI-Kurator und Quellen

Der KI-Kurator verwaltet pro Konto einen Zeitplan, Suchprofil, Chat-Verlauf
und Feedback-Signale. Die automatische Suche läuft über den Worker, solange
der Docker-Stack aktiv ist. Webfunde speichern nur Metadaten, kurze
Einordnung und den Original-Link. Der Dienst umgeht keine Paywalls, Logins,
Robots-Regeln oder Publisher-Beschränkungen.

Nach erfolgreichen KI-Funden merkt sich dérive die Publikations-Domain. Häufig
passende Quellen erhalten einen höheren Quellenwert; positives oder negatives
Feedback beeinflusst diesen Wert zusätzlich. Pro Lauf werden nur einige
etablierte Quellen verwendet und mit offener Websuche gemischt. Nicht jede
Quelle wird bei jedem Lauf abgefragt, sondern über die Zeit rotierend.

Im Bereich **KI-Kurator** erscheinen gelernte Quellen separat von den manuell
gedrosselten Quellen. Eine manuell gesetzte Regel hat Vorrang vor dem
automatischen Quellenwert. Neue manuelle Domains werden beim Hinzufügen sofort
gespeichert.

Optional kann `PEXELS_API_KEY` gesetzt werden. Dann wählt der Kurator für neue
Läufe ein passendes Hero-Bild von Pexels und zeigt stets Urheber und
Original-Link an.

## Entwicklung

```powershell
docker compose run --rm api pytest
docker compose run --rm web npm run typecheck
```

Alternativ lokal in den jeweiligen Projektordnern:

```powershell
cd apps/api
python -m pytest -q

cd ../web
npm ci
npm run typecheck
npm run build
```

Vor einem Deployment sollten API-Tests, TypeScript-Prüfung und der
Produktions-Build erfolgreich durchlaufen.
