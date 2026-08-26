export type Article = {
  id: number;
  title: string;
  dek: string | null;
  canonical_url: string;
  published_at: string;
  reading_minutes: number;
  topics: string[];
  image_url: string | null;
  image_credit: string | null;
  image_source_url: string | null;
  image_query: string | null;
  is_read: boolean;
  is_saved: boolean;
  author: string;
  source: string;
  source_url: string;
  discovery_method: "feed" | "ai_web" | string;
  curation_reason: string | null;
  discovered_at: string | null;
  access_status: "free" | "paywalled" | "subscriber" | "unknown" | string;
  fulltext_source: "feed" | "subscriber_capture" | string;
  rights_basis: "personal_subscription" | string | null;
  captured_at: string | null;
  content_html?: string;
  reason?: string;
};

export type PodcastEpisode = {
  id: number;
  title: string;
  show_name: string;
  description: string | null;
  canonical_url: string;
  spotify_url: string | null;
  is_saved: boolean;
  published_at: string;
  duration_minutes: number;
  topics: string[];
  curation_reason: string | null;
  discovered_at: string;
};

export type Home = {
  for_you: Article[];
  today: Article[];
  discover: Article[];
  podcasts: PodcastEpisode[];
  authors: { name: string; count: number }[];
  topics: { name: string; article_count: number }[];
  hero_visual: {
    url: string | null;
    source_url: string | null;
    credit: string | null;
    alt: string | null;
  };
};

export type Feed = {
  id: number;
  url: string;
  title: string;
  site_url: string | null;
  type: "rss" | "atom" | "json" | string;
  sync_status: "never" | "syncing" | "ok" | "error" | string;
  last_synced_at: string | null;
  last_error: string | null;
  article_count: number;
};

export type FeedPreview = {
  url: string;
  title: string;
  site_url: string | null;
  type: Feed["type"];
  article_count: number;
};

export type AISetup = {
  provider: "disabled" | "openai" | "openai_compatible" | "ollama";
  base_url: string | null;
  model: string | null;
  api_key?: string;
  has_api_key?: boolean;
};

export type AIConnectionResult = {
  connected: boolean;
  model_found: boolean;
  models: string[];
  message: string;
};

export type SetupStatus = {
  setup_completed: boolean;
  display_name: string;
  preferred_languages: string[];
  discovery_languages: string[];
  interests: string[];
  discovery_prompt: string;
  reading_length: "mixed" | "short" | "medium" | "long";
  theme: "system" | "light" | "dark";
  feed_count: number;
  ai: AISetup;
  pexels: { has_api_key: boolean };
  discovery: DiscoveryProfile;
};

export type SetupPayload = Omit<SetupStatus, "setup_completed" | "feed_count" | "ai" | "pexels" | "discovery"> & {
  discovery_prompt: string;
  ai: AISetup;
  pexels_api_key?: string;
};

export type DiscoveryProfile = {
  prompt: string;
  frequency: "manual" | "interval" | "daily" | "every_3_days" | "weekly";
  interval_days: number;
  delivery_time: string;
  timezone: string;
  min_minutes: number;
  max_articles: number;
  open_access_only: boolean;
  include_paywalled: boolean;
  deprioritized_sources: string[];
  last_run_at: string | null;
};

export type DiscoveryStatus = {
  profile: DiscoveryProfile;
  provider: AISetup["provider"];
  provider_ready: boolean;
  articles: Article[];
  podcasts: PodcastEpisode[];
  sources: DiscoverySource[];
  automation: {
    enabled: boolean;
    interval_days: number | null;
    delivery_time: string;
    timezone: string;
    background_interval_hours: number | null;
    next_due_at: string | null;
  };
  runs: DiscoveryRun[];
};

export type DiscoverySource = {
  domain: string;
  name: string;
  origin: "learned" | "manual" | string;
  status: "active" | "deprioritized" | "excluded" | string;
  observed_count: number;
  positive_count: number;
  negative_count: number;
  search_count: number;
  score: number;
  last_observed_at: string | null;
  last_selected_at: string | null;
};

export type DiscoveryRun = {
  id: number;
  trigger: "automatic" | "manual" | string;
  status: "success" | "failed" | string;
  imported_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  message: string | null;
  ran_at: string;
};

export type DiscoveryProgressEvent = {
  type: "progress";
  phase?: "articles" | "podcasts";
  batch: number;
  batches: number;
  searched: number;
  found_count: number;
  found: Article[];
  podcasts_found?: number;
  podcasts?: PodcastEpisode[];
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

export type DiscoveryChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  profile_suggestion: string | null;
  created_at: string;
};

export type DiscoveryChatStatus = {
  provider: AISetup["provider"];
  provider_ready: boolean;
  messages: DiscoveryChatMessage[];
};

export type DiscoveryChatResearch = {
  articles: Article[];
  podcasts: PodcastEpisode[];
  chat: DiscoveryChatStatus;
  discovery: DiscoveryStatus;
};

export type SetupResult = SetupStatus & {
};

export type ArticleFeedback = {
  id: number;
  article_id: number;
  article_title: string;
  source: string;
  rating: "great" | "yes" | "not_quite" | "no";
  note: string | null;
  created_at: string;
  updated_at: string | null;
};

export type ReadingProfile = {
  stats: { read_count: number; saved_count: number; feedback_count: number };
  feedback: ArticleFeedback[];
  insights: { key: string; text: string; basis: string }[];
};
