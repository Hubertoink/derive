from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    """A dérive account. Content metadata stays shared, reader state does not."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(16), default="member", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    invited_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserArticle(Base):
    __tablename__ = "user_articles"
    __table_args__ = (UniqueConstraint("user_id", "article_id", name="uq_user_articles_user_article"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserPodcastEpisode(Base):
    __tablename__ = "user_podcast_episodes"
    __table_args__ = (UniqueConstraint("user_id", "podcast_episode_id", name="uq_user_podcasts_user_episode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    podcast_episode_id: Mapped[int] = mapped_column(ForeignKey("podcast_episodes.id", ondelete="CASCADE"), index=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserFeed(Base):
    __tablename__ = "user_feeds"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_user_feeds_user_feed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserArticleFeedback(Base):
    __tablename__ = "user_article_feedback"
    __table_args__ = (UniqueConstraint("user_id", "article_id", name="uq_user_article_feedback"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    rating: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserReadingInsight(Base):
    __tablename__ = "user_reading_insights"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_reading_insight"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserPublisherAccessRule(Base):
    __tablename__ = "user_publisher_access_rules"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_publisher_rule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    publisher_name: Mapped[str] = mapped_column(String(255))
    domains_csv: Mapped[str] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_basis: Mapped[str] = mapped_column(String(64), default="personal_subscription")
    capture_method: Mapped[str] = mapped_column(String(64), default="browser_copy")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    articles: Mapped[list["Article"]] = relationship(back_populates="author")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    url: Mapped[str] = mapped_column(String(2048))
    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class UserSourceMemory(Base):
    """Per-reader memory for publishers discovered by AI curation."""

    __tablename__ = "user_source_memory"
    __table_args__ = (UniqueConstraint("user_id", "domain", name="uq_user_source_memory_user_domain"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    origin: Mapped[str] = mapped_column(String(16), default="learned")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    source_score: Mapped[int] = mapped_column(Integer, default=0)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    site_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    feed_type: Mapped[str] = mapped_column(String(32), default="rss")
    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(32), default="never")
    articles: Mapped[list["Article"]] = relationship(back_populates="feed")


class DiscoveryChatMessage(Base):
    __tablename__ = "discovery_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    profile_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleFeedback(Base):
    __tablename__ = "article_feedback"
    __table_args__ = (UniqueConstraint("article_id", name="uq_article_feedback_article"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    rating: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReadingInsight(Base):
    __tablename__ = "reading_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="automatic")
    status: Mapped[str] = mapped_column(String(16), default="success")
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PublisherAccessRule(Base):
    __tablename__ = "publisher_access_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    publisher_name: Mapped[str] = mapped_column(String(255))
    domains_csv: Mapped[str] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_basis: Mapped[str] = mapped_column(String(64), default="personal_subscription")
    capture_method: Mapped[str] = mapped_column(String(64), default="browser_copy")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    preferred_languages_csv: Mapped[str] = mapped_column(String(500), default="Deutsch,Englisch")
    discovery_languages_csv: Mapped[str] = mapped_column(String(500), default="Deutsch,Englisch")
    interests_csv: Mapped[str] = mapped_column(String(2000), default="")
    discovery_deprioritized_sources_csv: Mapped[str] = mapped_column(String(2000), default="")
    reading_length: Mapped[str] = mapped_column(String(32), default="mixed")
    theme: Mapped[str] = mapped_column(String(32), default="system")
    ai_provider: Mapped[str] = mapped_column(String(32), default="disabled")
    ai_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    pexels_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_client_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_prompt: Mapped[str] = mapped_column(
        Text,
        default="Lange Reportagen mit erzählerischer Tiefe, sorgfältiger Recherche und neuen Perspektiven.",
    )
    discovery_frequency: Mapped[str] = mapped_column(String(32), default="daily")
    discovery_interval_days: Mapped[int] = mapped_column(Integer, default=1)
    discovery_time: Mapped[str] = mapped_column(String(5), default="09:00")
    discovery_timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin")
    discovery_min_minutes: Mapped[int] = mapped_column(Integer, default=15)
    discovery_max_articles: Mapped[int] = mapped_column(Integer, default=5)
    discovery_open_access_only: Mapped[bool] = mapped_column(Boolean, default=True)
    discovery_include_paywalled: Mapped[bool] = mapped_column(Boolean, default=True)
    discovery_last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hero_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    hero_image_source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    hero_image_credit: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hero_image_alt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hero_image_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PodcastEpisode(Base):
    __tablename__ = "podcast_episodes"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_podcast_episodes_canonical_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    show_name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), index=True)
    spotify_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    topics_csv: Mapped[str] = mapped_column(String(500), default="")
    curation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), index=True)
    title: Mapped[str] = mapped_column(String(500))
    dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_html: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reading_minutes: Mapped[int] = mapped_column(Integer, default=5)
    topics_csv: Mapped[str] = mapped_column(String(500), default="")
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    image_credit: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    image_query: Mapped[str | None] = mapped_column(String(240), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fresh_rss_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    discovery_method: Mapped[str] = mapped_column(String(32), default="feed")
    curation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_status: Mapped[str] = mapped_column(String(32), default="unknown")
    fulltext_source: Mapped[str] = mapped_column(String(32), default="feed")
    rights_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feed_id: Mapped[int | None] = mapped_column(ForeignKey("feeds.id"), nullable=True, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    author: Mapped[Author] = relationship(back_populates="articles")
    source: Mapped[Source] = relationship(back_populates="articles")
    feed: Mapped[Feed | None] = relationship(back_populates="articles")
