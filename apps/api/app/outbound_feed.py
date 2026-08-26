"""Generate dérive's outbound RSS feed.

The feed deliberately publishes article metadata and curation context, not a copy
of the original article. Clicking an item therefore keeps the original author and
publication at the centre of the reading experience.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Callable
from urllib.parse import urljoin
from xml.etree import ElementTree

from .models import Article

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
READO_NAMESPACE = "https://reado.local/ns/1.0"

ElementTree.register_namespace("atom", ATOM_NAMESPACE)
ElementTree.register_namespace("dc", DC_NAMESPACE)
ElementTree.register_namespace("reado", READO_NAMESPACE)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _description(article: Article, reason: str) -> str:
    parts = []
    if article.dek:
        parts.append(f"<p>{html.escape(article.dek)}</p>")
    parts.append(f"<p><strong>dérive-Einordnung:</strong> {html.escape(reason)}</p>")
    parts.append(
        "<p>"
        f"{html.escape(article.author.name)} · {html.escape(article.source.name)} · "
        f"{article.reading_minutes} Min. Lesezeit"
        "</p>"
    )
    return "".join(parts)


def build_rss_feed(
    articles: list[Article],
    *,
    public_url: str,
    reason_for: Callable[[Article], str],
) -> bytes:
    """Build a standards-compatible RSS 2.0 document for curated articles."""
    base_url = public_url.rstrip("/") + "/"
    feed_url = urljoin(base_url, "feed.xml")
    root = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(root, "channel")
    ElementTree.SubElement(channel, "title").text = "dérive – Deine kuratierte Leseliste"
    ElementTree.SubElement(channel, "link").text = base_url
    ElementTree.SubElement(channel, "description").text = (
        "Hochwertige Artikel und neue Perspektiven, kuratiert von dérive."
    )
    ElementTree.SubElement(channel, "language").text = "de-DE"
    ElementTree.SubElement(channel, "generator").text = "dérive"
    ElementTree.SubElement(channel, "ttl").text = "15"
    ElementTree.SubElement(
        channel,
        ElementTree.QName(ATOM_NAMESPACE, "link"),
        {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )

    if articles:
        newest = max(_utc(article.published_at) for article in articles)
        ElementTree.SubElement(channel, "lastBuildDate").text = format_datetime(newest)

    for article in articles:
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = article.title
        ElementTree.SubElement(item, "link").text = article.canonical_url
        ElementTree.SubElement(
            item, "guid", {"isPermaLink": "true"}
        ).text = article.canonical_url
        ElementTree.SubElement(item, "pubDate").text = format_datetime(
            _utc(article.published_at)
        )
        ElementTree.SubElement(item, "description").text = _description(
            article, reason_for(article)
        )
        ElementTree.SubElement(
            item, ElementTree.QName(DC_NAMESPACE, "creator")
        ).text = article.author.name
        for topic in (topic.strip() for topic in article.topics_csv.split(",")):
            if topic:
                ElementTree.SubElement(item, "category").text = topic
        ElementTree.SubElement(
            item, ElementTree.QName(READO_NAMESPACE, "source")
        ).text = article.source.name
        ElementTree.SubElement(
            item, ElementTree.QName(READO_NAMESPACE, "sourceUrl")
        ).text = article.source.url
        ElementTree.SubElement(
            item, ElementTree.QName(READO_NAMESPACE, "readerUrl")
        ).text = urljoin(base_url, f"artikel/{article.id}")
        ElementTree.SubElement(
            item, ElementTree.QName(READO_NAMESPACE, "readingMinutes")
        ).text = str(article.reading_minutes)

    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
