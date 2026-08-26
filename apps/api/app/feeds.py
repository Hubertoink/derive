"""Safe feed fetching, parsing, and HTML sanitisation for native feeds."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

MAX_FEED_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
ALLOWED_TAGS = {
    "p", "br", "div", "span", "article", "section", "h1", "h2", "h3", "h4",
    "h5", "h6", "blockquote", "ul", "ol", "li", "strong", "em", "b", "i",
    "u", "s", "a", "img", "figure", "figcaption", "pre", "code", "hr",
}
ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
}


@dataclass
class ParsedItem:
    external_id: str
    url: str
    title: str
    author: str
    content_html: str
    published_at: datetime


@dataclass
class ParsedFeed:
    feed_type: str
    title: str
    site_url: str | None
    items: list[ParsedItem]


def validate_public_url(value: str) -> str:
    """Return a normalised public HTTP URL or raise ValueError."""
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only public http:// and https:// URLs are supported.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not allowed.")
    if not parsed.hostname or len(value) > 2048:
        raise ValueError("The URL is invalid.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ValueError("Localhost URLs are not allowed.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except (OSError, ValueError):
        raise ValueError("The feed host could not be resolved.") from None
    if not addresses:
        raise ValueError("The feed host could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, local, link-local, and reserved addresses are not allowed.")
    return parsed._replace(fragment="").geturl()


async def fetch_feed(url: str, *, etag: str | None = None, last_modified: str | None = None) -> tuple[bytes, httpx.Headers, int]:
    validate_public_url(url)
    headers = {"Accept": "application/feed+json, application/json, application/atom+xml, application/rss+xml, application/xml, text/xml, */*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, follow_redirects=False, trust_env=False, headers=headers
    ) as client:
        async with client.stream("GET", url) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("The feed redirected; confirm the final public URL before adding it.")
            if response.status_code == 304:
                return b"", response.headers, response.status_code
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and int(length) > MAX_FEED_BYTES:
                raise ValueError("The feed response is too large.")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise ValueError("The feed response is too large.")
                chunks.append(chunk)
            return b"".join(chunks), response.headers, response.status_code


def _local(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element.iter() if child.tag.rsplit("}", 1)[-1].lower() == name]


def _text(element: ElementTree.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _date(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return datetime.now(UTC)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _link(elements: list[ElementTree.Element], fallback: str = "") -> str:
    for link in elements:
        href = link.attrib.get("href")
        if href and link.attrib.get("rel", "alternate") == "alternate":
            return href
        if link.text and not link.attrib:
            return link.text.strip()
    return fallback


def _first(elements: list[ElementTree.Element]) -> ElementTree.Element | None:
    return elements[0] if elements else None


def _first_available(*elements: list[ElementTree.Element]) -> ElementTree.Element | None:
    for candidates in elements:
        if candidates:
            return candidates[0]
    return None


def parse_xml_feed(data: bytes) -> ParsedFeed:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("The response is not valid XML.") from error
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name == "feed":
        title = _text(next(iter(_local(root, "title")), None)) or "Untitled feed"
        site_url = _link(_local(root, "link")) or None
        entries = _local(root, "entry")
        items: list[ParsedItem] = []
        for index, entry in enumerate(entries):
            url = _link(_local(entry, "link"))
            if not url:
                continue
            content = _first_available(_local(entry, "content"), _local(entry, "summary"))
            author_element = next(iter(_local(entry, "author")), None)
            author = _text(next(iter(_local(author_element, "name")), None)) if author_element is not None else ""
            external_id = _text(next(iter(_local(entry, "id")), None)) or url or str(index)
            items.append(ParsedItem(external_id, url, _text(next(iter(_local(entry, "title")), None)) or "Untitled", author or "Unknown author", sanitize_html(_text(content)), _date(_text(next(iter(_local(entry, "published")), None)) or _text(next(iter(_local(entry, "updated")), None)))))
        return ParsedFeed("atom", title, site_url, items)
    channel = next(iter(_local(root, "channel")), root)
    title = _text(next(iter(_local(channel, "title")), None)) or "Untitled feed"
    site_url = _text(next(iter(_local(channel, "link")), None)) or None
    items = []
    for index, item in enumerate(_local(channel, "item")):
        url = _text(next(iter(_local(item, "link")), None))
        if not url:
            continue
        guid = _text(next(iter(_local(item, "guid")), None)) or url or str(index)
        content = _first_available(_local(item, "encoded"), _local(item, "description"), _local(item, "summary"))
        items.append(ParsedItem(guid, url, _text(next(iter(_local(item, "title")), None)) or "Untitled", _text(next(iter(_local(item, "creator")), None)) or "Unknown author", sanitize_html(_raw_text(content)), _date(_text(next(iter(_local(item, "pubdate")), None)))))
    return ParsedFeed("rss", title, site_url, items)


def _raw_text(element: ElementTree.Element | None) -> str:
    return "".join(element.itertext()) if element is not None else ""


def parse_json_feed(data: bytes) -> ParsedFeed:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The response is not valid JSON Feed.") from error
    if not isinstance(payload, dict) or not str(payload.get("version", "")).startswith("https://jsonfeed.org/version/"):
        raise ValueError("The response is not a supported JSON Feed.")
    items: list[ParsedItem] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict) or not item.get("id") or not (item.get("url") or item.get("external_url")):
            continue
        content = item.get("content_html") or item.get("content_text") or item.get("summary") or ""
        author = item.get("author") or {}
        author_name = author.get("name") if isinstance(author, dict) else ""
        items.append(ParsedItem(str(item["id"]), str(item.get("url") or item["external_url"]), str(item.get("title") or "Untitled"), str(author_name or "Unknown author"), sanitize_html(str(content)), _date(str(item.get("date_published") or item.get("date_modified") or ""))))
    return ParsedFeed("json", str(payload.get("title") or "Untitled feed"), str(payload.get("home_page_url")) if payload.get("home_page_url") else None, items)


def parse_feed(data: bytes, content_type: str = "") -> ParsedFeed:
    if "json" in content_type.lower() or data.lstrip().startswith(b"{"):
        return parse_json_feed(data)
    return parse_xml_feed(data)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            if tag in {"script", "style", "iframe", "object", "embed", "svg", "math"}:
                self.skip += 1
            return
        clean: list[str] = []
        for key, value in attrs:
            key = key.lower()
            if key not in ALLOWED_ATTRS.get(tag, set()) or value is None:
                continue
            if key in {"href", "src"}:
                parsed = urlparse(value.strip())
                if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password:
                    continue
            clean.append(f' {key}="{html.escape(value, quote=True)}"')
        self.output.append(f"<{tag}{''.join(clean)}>")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "iframe", "object", "embed", "svg", "math"} and self.skip:
            self.skip -= 1
        elif tag.lower() in ALLOWED_TAGS:
            self.output.append(f"</{tag.lower()}>")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.output.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self.skip:
            self.output.append(f"&{name};")


def sanitize_html(value: str) -> str:
    parser = _Sanitizer()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()
