# ReadO – Design Guidelines

## Leitidee

ReadO ist ein ruhiger, entschlossener Leseraum. Das Interface gibt Inhalten eine Bühne: große Typografie, klare Hierarchie und wenige, bewusst gesetzte Interaktionen. Die Gestaltung ist editorial, direkt und taktil – nie dekorativ um ihrer selbst willen.

## Grundprinzipien

1. **Text führt.** Überschriften und Lesetext tragen die visuelle Identität. Bilder unterstützen einen Inhalt, ersetzen ihn aber nicht.
2. **Klar statt weich.** Flächen, Linien und Kontraste strukturieren die Seite. Abgerundete Komponenten werden vermieden; die Ausnahme sind runde Icon-Trigger.
3. **Wenige starke Entscheidungen.** Jede Seite hat eine dominante Geschichte oder Handlung. Sekundäre Informationen bleiben optisch zurückhaltend.
4. **Bewegung zeigt Beziehung.** Animationen erklären, woher ein Element kommt und wohin es gehört. Sie sind kurz, dezent und überspringbar.
5. **Lesen ist kein Dashboard.** Keine überladene Datenansicht, keine konkurrierenden Karten, keine unnötigen Statusanzeigen.

## Farbwelt

| Token | Wert | Einsatz |
| --- | --- | --- |
| `--porcelain` | `#fffcf7` | Standard-Hintergrund, helle Freiräume |
| `--ink` | `#26343b` | Text, Regeln, primäre Aktionen |
| `--slate-grey` | `#738290` | Zurückhaltende Navigation und Metadaten |
| `--powder-blue` | `#a1b5d8` | Einzelne hervorgehobene Flächen |
| `--frosted-mint` | `#e4f0d0` | Sanfte Auswahl, positive Markierung |
| `--tea-green` | `#c2d8b9` | Große Abschluss- oder Listenflächen |

Nutze maximal eine farbige Fläche pro Inhaltsgruppe. `--ink` auf `--porcelain` ist die Standardkombination. Farbige Flächen brauchen keine zusätzlichen Schatten oder Verläufe.

## Typografie

- **Display und Inhalte:** `Georgia, "Times New Roman", serif`. Große, normale Schnitte; enges Letterspacing bei Überschriften (`-0.04em` bis `-0.06em`).
- **Navigation und Metadaten:** `Arial, Helvetica, sans-serif`. Klein, präzise, mit erhöhter Laufweite.
- **Überschriften:** groß, kompakt und maximal zweizeilig, wenn möglich. Keine zusätzliche Über-Überschrift; ein kurzer Kicker reicht zur Einordnung.
- **Kicker:** Großbuchstaben, etwa `0.67rem`, fett, `0.15em` Laufweite.
- **Fließtext:** Serif, großzügige Zeilenhöhe (mindestens `1.4`). Lesbarkeit hat Vorrang vor Informationsdichte.

## Layout und Flächen

- Seitenbreite: `min(1280px, calc(100% - 64px))`; mobil `calc(100% - 32px)`.
- Nutze Regeln (`1px` oder `2px`) als primäre Trennung statt Karten mit Radius oder Schatten.
- Der wichtigste Artikel einer Seite bekommt eine große Bildfläche und deutliche Textüberlagerung.
- Empfehlungen sind als Raster oder direkte Liste angelegt, nicht als schwebende Karten.
- Großzügiger vertikaler Abstand ist Teil der Hierarchie: neue Inhaltsgruppen beginnen meist mit `68–100px` Abstand.

## Komponenten

### Hero-Artikel

Ein Hero kombiniert ein großes Bild, einen dunklen lesefördernden Verlauf, Quelle/Lesezeit, Titel, Autor und CTA. Der Titel steht sichtbar über dem Bild. Der CTA ist eine flache, kontrastierende Fläche ohne Radius.

### Auswahlkarten

Wöchentliche Auswahlkarten liegen direkt aneinander und werden durch Linien getrennt. Eine Karte darf farbig hinterlegt werden; nummeriere sie dezent groß im Hintergrund.

### Aktionen und Menüs

Normale Textaktionen sind flach, klein und klar beschriftet. Der globale Schnellzugriff ist die einzige bewusst runde Ausnahme:

- Verwende Tabler Icons mit feiner Konturstärke (`1.6–1.8`).
- Desktop: runder Trigger mittig am rechten Rand; Aktionen fahren nach links aus.
- Mobil: Trigger zentriert am unteren Rand; Aktionen fahren nach oben aus.
- Der Trigger wechselt beim Öffnen sanft von Plus zu Schließen. Aktionen erscheinen mit kurzem, gestaffeltem Fade/Scale.
- Icon-Aktionen erhalten immer zugängliche Namen und einen unaufdringlichen Label-Hinweis beim Hover/Fokus.
- Respektiere `prefers-reduced-motion`; vermeide dramatische oder dauerhafte Bewegung.

## Interaktion und Accessibility

- Alle interaktiven Elemente brauchen sichtbaren Tastaturfokus.
- Menüs vermitteln ihren geöffneten Zustand über `aria-expanded` und sind mit `Escape` schließbar.
- Icons ohne sichtbaren Text benötigen einen zugänglichen Namen.
- Bilder bekommen prägnante, inhaltliche Alternativtexte.
- Verlasse dich nie ausschließlich auf Farbe, um Bedeutung oder Status zu vermitteln.

## Vermeiden

- Pill-Buttons, abgerundete Karten und übermäßige Box-Schatten
- Mehrere konkurrierende Primär-CTAs in einem Bereich
- Generische Marketing-Sprache und lange Oberzeilen
- Zu viele Icon-Familien oder gefüllte, schwere Icons
- Animationen, die Inhalt verdecken, verzögern oder Aufmerksamkeit erzwingen
