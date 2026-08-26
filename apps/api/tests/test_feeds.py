from datetime import UTC, datetime
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.feeds import ParsedFeed, ParsedItem, parse_feed, sanitize_html, validate_public_url
from app.main import add_items
from app.models import Article, Author, Feed, Source


def test_parses_rss_atom_and_json_feed():
    rss = b'<rss><channel><title>RSS</title><item><guid>1</guid><link>https://example.com/1</link><title>One</title><description><![CDATA[<p>Body</p>]]></description></item></channel></rss>'
    atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><id>a</id><title>Two</title><link href="https://example.com/2"/><content type="html">&lt;p&gt;Body&lt;/p&gt;</content></entry></feed>'
    json_feed = b'{"version":"https://jsonfeed.org/version/1","title":"JSON","items":[{"id":"j","url":"https://example.com/3","title":"Three","content_html":"<p>Body</p>"}]}'
    assert parse_feed(rss).feed_type == "rss"
    assert parse_feed(atom).feed_type == "atom"
    assert parse_feed(json_feed).feed_type == "json"


def test_sanitizes_imported_html():
    clean = sanitize_html('<p>Hello</p><script>alert(1)</script><a href="javascript:alert(1)">bad</a>')
    assert clean == '<p>Hello</p><a>bad</a>'
    assert "script" not in clean.lower()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost/feed", "http://127.0.0.1/feed", "https://user:pass@example.com/feed"])
def test_blocks_unsafe_feed_urls(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_deduplicates_items_per_feed():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        feed = Feed(url="https://example.com/feed", title="Example")
        session.add(feed)
        session.flush()
        parsed = ParsedFeed("rss", "Example", "https://example.com", [
            ParsedItem("one", "https://example.com/one", "One", "Author", "<p>Body</p>", datetime.now(UTC)),
        ])
        assert add_items(session, feed, parsed) == 1
        session.flush()
        assert add_items(session, feed, parsed) == 0
        assert session.scalar(select(func.count()).select_from(Article)) == 1


def test_reuses_new_authors_and_sources_within_one_feed_import():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        feed = Feed(url="https://example.com/feed", title="Example")
        session.add(feed)
        session.flush()
        parsed = ParsedFeed("rss", "Example", "https://example.com", [
            ParsedItem("one", "https://example.com/one", "One", "Same author", "<p>One</p>", datetime.now(UTC)),
            ParsedItem("two", "https://example.com/two", "Two", "Same author", "<p>Two</p>", datetime.now(UTC)),
        ])

        assert add_items(session, feed, parsed) == 2
        session.commit()
        assert session.scalar(select(func.count()).select_from(Article)) == 2
        assert session.scalar(select(func.count()).select_from(Author)) == 1
        assert session.scalar(select(func.count()).select_from(Source)) == 1


def test_skips_duplicate_article_urls_within_one_feed_response():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        feed = Feed(url="https://example.com/feed", title="Example")
        session.add(feed)
        session.flush()
        published_at = datetime.now(UTC)
        parsed = ParsedFeed("rss", "Example", "https://example.com", [
            ParsedItem("one", "https://example.com/one", "One", "Author", "<p>One</p>", published_at),
            ParsedItem("two", "https://example.com/one", "Duplicate", "Author", "<p>Two</p>", published_at),
        ])

        assert add_items(session, feed, parsed) == 1
        session.commit()
        assert session.scalar(select(func.count()).select_from(Article)) == 1
