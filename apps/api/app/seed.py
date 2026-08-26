from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Article, Author, Source


def seed_demo_content(session: Session) -> None:
    """Insert deterministic fixtures for tests only.

    Production startup deliberately does not call this function; a fresh
    dérive instance should begin with the user's feeds, not demo articles.
    """
    if session.scalar(select(Article.id).limit(1)) is not None:
        return

    now = datetime.now(UTC)
    essays = [
        {
            "title": "Die stille Infrastruktur des Denkens",
            "dek": "Warum Bibliotheken, Notizbuecher und wiederholtes Lesen keine nostalgischen Werkzeuge sind.",
            "content": "<p>Das Denken beginnt selten mit einer Antwort. Es beginnt mit einer Umgebung, die Fragen aushalten kann.</p><p>Bibliotheken sind nicht bloss Speicher. Sie sind ein Vorschlag zur Geduld: Regale machen sichtbar, dass jede Gegenwart von vielen, oft widerspruechlichen Stimmen umgeben ist.</p><p>Wer liest, nimmt sich Zeit fuer die genaue Form eines Arguments. Diese Aufmerksamkeit ist keine Flucht aus der Welt, sondern eine Weise, ihr gerechter zu werden.</p>",
            "author": "Mara Voss",
            "source": "Neue Gegenwart",
            "source_url": "https://example.org/neue-gegenwart",
            "url": "https://example.org/die-stille-infrastruktur-des-denkens",
            "topics": "Lesen, Kultur, Gesellschaft",
            "minutes": 12,
            "age_hours": 2,
        },
        {
            "title": "Technologie als Frage der Wartung",
            "dek": "Nicht die Erfindung, sondern die Pflege entscheidet, welche Technik dauerhaft Teil einer Gesellschaft wird.",
            "content": "<p>Von Technik sprechen wir gern im Ton des Anfangs. Es gibt eine Neuheit, einen Durchbruch, eine Zukunft.</p><p>Doch die meisten technischen Systeme leben nicht von ihrer Premiere. Sie leben von Menschen, die sie prüfen, reparieren und an veränderte Umstände anpassen.</p><p>Eine Kultur der Wartung fragt nicht nur, was möglich ist. Sie fragt, was erhalten werden soll und wer die Verantwortung dafür trägt.</p>",
            "author": "Jonas Rehm",
            "source": "Werkstatt",
            "source_url": "https://example.org/werkstatt",
            "url": "https://example.org/technologie-als-frage-der-wartung",
            "topics": "Technologie, Gesellschaft, Arbeit",
            "minutes": 9,
            "age_hours": 6,
        },
        {
            "title": "Nach dem letzten Konzert",
            "dek": "Ueber das Zuhoeren, das im Gedächtnis weitergeht, wenn der Saal bereits leer ist.",
            "content": "<p>Ein Konzert endet nicht mit dem letzten Ton. Es endet erst, wenn die Stille im Raum wieder eine eigene Form angenommen hat.</p><p>Vielleicht ist das der Grund, weshalb Musik uns so lange begleitet: Sie organisiert Zeit, ohne sie festzuhalten.</p><p>Das Erinnern an ein Klangereignis ist keine Kopie. Es ist eine zweite, persoenliche Auffuehrung.</p>",
            "author": "Elif Demir",
            "source": "Takt",
            "source_url": "https://example.org/takt",
            "url": "https://example.org/nach-dem-letzten-konzert",
            "topics": "Musik, Kultur, Erinnerung",
            "minutes": 7,
            "age_hours": 12,
        },
        {
            "title": "Die produktive Zumutung der Gegenposition",
            "dek": "Ein Plädoyer fuer Debatten, die das bessere Argument suchen statt schnelle Zustimmung.",
            "content": "<p>Eine Gegenposition ist keine Stoerung des Gespraechs. Sie kann dessen Bedingung sein.</p><p>Wo nur Zustimmung erwartet wird, verliert das Denken seine Beweglichkeit. Widerspruch zwingt uns, Begriffe genauer zu fassen und Voraussetzungen sichtbar zu machen.</p><p>Das Ziel ist nicht der dauerhafte Konflikt, sondern ein genauerer gemeinsamer Blick.</p>",
            "author": "Mara Voss",
            "source": "Neue Gegenwart",
            "source_url": "https://example.org/neue-gegenwart",
            "url": "https://example.org/die-produktive-zumutung-der-gegenposition",
            "topics": "Gesellschaft, Politik, Denken",
            "minutes": 10,
            "age_hours": 28,
        },
        {
            "title": "Eine Karte fuer unbekannte Wege",
            "dek": "Was wir von Stadtspaziergaengen ueber Neugier und Orientierung lernen koennen.",
            "content": "<p>Karten versprechen Uebersicht. Gute Wege erlauben dennoch, sich zu verirren.</p><p>Wer eine Stadt nur nach Effizienz durchquert, sieht ihre Verbindungen nicht. Ein Umweg kann ein Viertel, eine Geschichte oder eine neue Frage freilegen.</p><p>Orientierung bedeutet nicht, alles vorauszusehen. Sie bedeutet, mit dem Unbekannten umgehen zu koennen.</p>",
            "author": "Leonie Hart",
            "source": "Randnotiz",
            "source_url": "https://example.org/randnotiz",
            "url": "https://example.org/eine-karte-fuer-unbekannte-wege",
            "topics": "Stadt, Kultur, Entdecken",
            "minutes": 6,
            "age_hours": 36,
        },
    ]

    authors: dict[str, Author] = {}
    sources: dict[str, Source] = {}
    for essay in essays:
        author = authors.setdefault(essay["author"], Author(name=essay["author"]))
        source = sources.setdefault(
            essay["source"], Source(name=essay["source"], url=essay["source_url"])
        )
        session.add(
            Article(
                canonical_url=essay["url"],
                title=essay["title"],
                dek=essay["dek"],
                content_html=essay["content"],
                published_at=now - timedelta(hours=essay["age_hours"]),
                reading_minutes=essay["minutes"],
                topics_csv=essay["topics"],
                author=author,
                source=source,
            )
        )
    session.commit()

