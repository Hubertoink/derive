import { createServer } from "node:http";

const discoveryProfile = {
  prompt: "",
  frequency: "manual",
  interval_days: 1,
  delivery_time: "09:00",
  timezone: "Europe/Berlin",
  min_minutes: 15,
  max_articles: 3,
  open_access_only: false,
  include_paywalled: true,
  last_run_at: null,
};

const setup = {
  setup_completed: false,
  display_name: "",
  preferred_languages: ["de"],
  discovery_languages: ["de", "en"],
  interests: [],
  discovery_prompt: "",
  reading_length: "mixed",
  theme: "system",
  feed_count: 0,
  ai: { provider: "disabled", base_url: null, model: null, has_api_key: false },
  pexels: { has_api_key: false },
  discovery: discoveryProfile,
};

const home = {
  for_you: [],
  today: [],
  discover: [],
  podcasts: [],
  artwork: null,
  authors: [],
  topics: [],
  hero_visual: { url: null, source_url: null, credit: null, alt: null },
};

const discovery = {
  profile: discoveryProfile,
  provider: "disabled",
  provider_ready: false,
  articles: [],
  podcasts: [],
  sources: [],
  automation: {
    enabled: false,
    interval_days: null,
    delivery_time: "09:00",
    timezone: "Europe/Berlin",
    next_due_at: null,
  },
  runs: [],
};

const payloadFor = (pathname) => {
  if (pathname === "/api/v1/setup") return setup;
  if (pathname === "/api/v1/home") return home;
  if (pathname === "/api/v1/articles") return [];
  if (pathname === "/api/v1/podcasts") return [];
  if (pathname === "/api/v1/feeds") return [];
  if (pathname === "/api/v1/discovery") return discovery;
  if (pathname === "/api/v1/discovery/chat") return { provider: "disabled", provider_ready: false, messages: [] };
  if (pathname === "/api/v1/publisher-access") return [];
  if (pathname === "/api/v1/reading-profile") {
    return {
      stats: { read_count: 0, saved_count: 0, feedback_count: 0 },
      soul: { markdown: "", revision: 0, art_enabled: true, revisions: [] },
      feedback: [],
      podcast_feedback: [],
      artwork_feedback: [],
      insights: [],
    };
  }
  return null;
};

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (url.pathname === "/api/v1/feed.xml") {
    response.writeHead(200, { "content-type": "application/rss+xml; charset=utf-8" });
    response.end("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>ReadO</title></channel></rss>");
    return;
  }

  const payload = payloadFor(url.pathname);
  response.writeHead(payload === null ? 404 : 200, { "content-type": "application/json" });
  response.end(JSON.stringify(payload ?? { detail: "Not found" }));
});

server.listen(4173, "127.0.0.1");

const close = () => {
  server.close();
  process.exit(0);
};
process.on("SIGINT", close);
process.on("SIGTERM", close);
