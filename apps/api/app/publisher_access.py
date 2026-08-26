"""Personal-subscription allowlist and explicit browser-copy imports."""

from __future__ import annotations

from datetime import UTC, datetime
import html
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .feeds import plain_text, sanitize_html, validate_public_url
from .models import Article, Author, PublisherAccessRule, Source, User, UserArticle, UserPublisherAccessRule


DEFAULT_RULES = (
    ("zeit", "DIE ZEIT", "zeit.de,www.zeit.de"),
    ("new-yorker", "The New Yorker", "newyorker.com,www.newyorker.com"),
    ("wired", "WIRED", "wired.com,www.wired.com"),
)
TERMS_URLS = {
    "zeit": "https://agb.zeit.de/abo",
    "new-yorker": "https://www.condenast.com/user-agreement",
    "wired": "https://www.condenast.com/user-agreement",
}
MAX_CAPTURE_BYTES = 2 * 1024 * 1024


class PublisherAccessError(ValueError):
    pass


def ensure_default_rules(session: Session, user: User | None = None) -> list[PublisherAccessRule | UserPublisherAccessRule]:
    model = UserPublisherAccessRule if user else PublisherAccessRule
    query = select(model)
    if user:
        query = query.where(UserPublisherAccessRule.user_id == user.id)
    existing = {rule.key: rule for rule in session.scalars(query).all()}
    changed = False
    for key, name, domains in DEFAULT_RULES:
        if key not in existing:
            attributes = {
                "key": key,
                "publisher_name": name,
                "domains_csv": domains,
                "rights_basis": "personal_subscription",
                "capture_method": "browser_copy",
            }
            if user:
                attributes["user_id"] = user.id
            rule = model(**attributes)
            session.add(rule)
            existing[key] = rule
            changed = True
    if changed:
        session.commit()
    return [existing[key] for key, _, _ in DEFAULT_RULES]


def serialize_rule(rule: PublisherAccessRule | UserPublisherAccessRule) -> dict:
    return {
        "key": rule.key,
        "publisher_name": rule.publisher_name,
        "domains": [domain.strip() for domain in rule.domains_csv.split(",") if domain.strip()],
        "enabled": rule.enabled,
        "terms_confirmed": rule.terms_confirmed,
        "rights_basis": rule.rights_basis,
        "capture_method": rule.capture_method,
        "terms_url": TERMS_URLS.get(rule.key),
    }


def update_rule(
    session: Session, key: str, *, enabled: bool, terms_confirmed: bool, user: User | None = None
) -> PublisherAccessRule | UserPublisherAccessRule:
    ensure_default_rules(session, user)
    model = UserPublisherAccessRule if user else PublisherAccessRule
    query = select(model).where(model.key == key)
    if user:
        query = query.where(UserPublisherAccessRule.user_id == user.id)
    rule = session.scalar(query)
    if rule is None:
        raise PublisherAccessError("Diese Publikation ist nicht in der Allowlist.")
    if enabled and not terms_confirmed:
        raise PublisherAccessError(
            "Bestätige zuerst, dass du einen persönlichen Zugriff hast und die lokale Kopie verwenden darfst."
        )
    rule.enabled = enabled
    rule.terms_confirmed = terms_confirmed
    session.commit()
    session.refresh(rule)
    return rule


def _matching_rule(session: Session, url: str, user: User | None = None) -> tuple[PublisherAccessRule | UserPublisherAccessRule, str]:
    canonical_url = validate_public_url(url)
    hostname = (urlparse(canonical_url).hostname or "").lower().rstrip(".")
    for rule in ensure_default_rules(session, user):
        domains = [domain.lower().rstrip(".") for domain in rule.domains_csv.split(",")]
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            if not rule.enabled or not rule.terms_confirmed:
                raise PublisherAccessError(
                    f"{rule.publisher_name} ist noch nicht für persönliche Abo-Importe freigeschaltet."
                )
            return rule, canonical_url
    raise PublisherAccessError("Die Artikel-Domain ist nicht in der Publisher-Allowlist.")


def _published_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def import_subscriber_article(
    session: Session,
    *,
    url: str,
    title: str,
    author_name: str,
    content_html: str,
    published_at: str | None,
    user: User | None = None,
) -> Article:
    if len(content_html.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise PublisherAccessError("Der Browser-Import ist größer als 2 MB.")
    rule, canonical_url = _matching_rule(session, url, user)
    if "<" not in content_html:
        paragraphs = [part.strip() for part in content_html.replace("\r\n", "\n").split("\n\n") if part.strip()]
        content_html = "".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)
    clean_content = sanitize_html(content_html)
    word_count = len(plain_text(clean_content).split())
    if word_count < 80:
        raise PublisherAccessError(
            "Der sichtbare Artikeltext ist zu kurz. Öffne den vollständigen Artikel im Browser und kopiere ihn erneut."
        )
    clean_title = plain_text(title)[:500] or "Unbenannter Artikel"
    clean_author = plain_text(author_name)[:255] or "Unbekannter Autor"
    now = datetime.now(UTC)

    article = session.scalar(select(Article).where(Article.canonical_url == canonical_url))
    if article is None:
        source = session.scalar(select(Source).where(Source.name == rule.publisher_name))
        if source is None:
            parsed = urlparse(canonical_url)
            source = Source(
                name=rule.publisher_name,
                url=f"{parsed.scheme}://{parsed.netloc}",
            )
            session.add(source)
        author = session.scalar(select(Author).where(Author.name == clean_author))
        if author is None:
            author = Author(name=clean_author)
            session.add(author)
        article = Article(
            canonical_url=canonical_url,
            title=clean_title,
            dek=plain_text(clean_content)[:500] or None,
            content_html=clean_content,
            published_at=_published_at(published_at),
            reading_minutes=max(1, word_count // 220),
            discovery_method="subscriber_import",
            access_status="subscriber",
            fulltext_source="subscriber_capture",
            rights_basis="personal_subscription",
            captured_at=now,
            author=author,
            source=source,
        )
        session.add(article)
    else:
        article.title = clean_title
        article.content_html = clean_content
        article.reading_minutes = max(1, word_count // 220)
        article.discovery_method = "subscriber_import"
        article.access_status = "subscriber"
        article.fulltext_source = "subscriber_capture"
        article.rights_basis = "personal_subscription"
        article.captured_at = now
    session.commit()
    session.refresh(article)
    if user and session.scalar(select(UserArticle.id).where(UserArticle.user_id == user.id, UserArticle.article_id == article.id)) is None:
        session.add(UserArticle(user_id=user.id, article_id=article.id, discovered_at=now))
        session.commit()
    return article
