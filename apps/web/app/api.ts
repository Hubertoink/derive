import { AIConnectionResult, AISetup, Article, ArticleFeedback, DiscoveryChatResearch, DiscoveryChatStatus, DiscoveryProfile, DiscoveryProgressEvent, DiscoveryStatus, Home, PodcastEpisode, PreferenceFeedback, PreferenceReason, ReadingProfile, SetupPayload, SetupResult, SetupStatus, SpotifyConnectionResult, SpotifySetup } from "./types";

// Empty by default: Next.js proxies /api/v1 to the internal API container.
// A public API URL remains possible for local development only.
const browserApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

function browserFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${browserApiUrl}${path}`, { ...init, credentials: "include" });
}

export async function getHome(): Promise<Home> {
  const response = await browserFetch("/api/v1/home", { cache: "no-store" });
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<Home>;
}

export async function getSetup(): Promise<SetupStatus> {
  const response = await browserFetch("/api/v1/setup", { cache: "no-store" });
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<SetupStatus>;
}

export async function getArticle(id: string): Promise<Article> {
  const response = await browserFetch(`/api/v1/articles/${id}`, { cache: "no-store" });
  if (response.status === 404) throw new Error("Dieser Artikel wurde nicht gefunden.");
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<Article>;
}

async function apiError(response: Response): Promise<never> {
  let detail = `dérive API returned ${response.status}.`;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) detail = body.detail;
  } catch {
    // Keep the status message when the response is not JSON.
  }
  throw new Error(detail);
}

export async function getArticles(): Promise<Article[]> {
  const response = await browserFetch("/api/v1/articles", { cache: "no-store" });
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<Article[]>;
}

export async function getPodcasts(): Promise<PodcastEpisode[]> {
  const response = await browserFetch("/api/v1/podcasts", { cache: "no-store" });
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<PodcastEpisode[]>;
}

export async function getPodcast(id: string): Promise<PodcastEpisode> {
  const response = await browserFetch(`/api/v1/podcasts/${id}`, { cache: "no-store" });
  if (response.status === 404) throw new Error("Diese Audio-Empfehlung wurde nicht gefunden.");
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response.json() as Promise<PodcastEpisode>;
}

export async function saveSetup(payload: SetupPayload): Promise<SetupResult> {
  const response = await browserFetch("/api/v1/setup", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<SetupResult>;
}

export async function testAI(ai: AISetup): Promise<AIConnectionResult> {
  const response = await browserFetch("/api/v1/setup/ai/test", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ai),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<AIConnectionResult>;
}

export async function testSpotify(spotify: SpotifySetup): Promise<SpotifyConnectionResult> {
  const response = await browserFetch("/api/v1/setup/spotify/test", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spotify),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<SpotifyConnectionResult>;
}

export async function getArticleFeedback(articleId: number): Promise<ArticleFeedback | null> {
  const response = await browserFetch(`/api/v1/articles/${articleId}/feedback`, { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<ArticleFeedback | null>;
}

export async function saveArticleFeedback(articleId: number, feedback: { rating: ArticleFeedback["rating"]; reasons?: PreferenceReason[]; note?: string }): Promise<ArticleFeedback> {
  const response = await browserFetch(`/api/v1/articles/${articleId}/feedback`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(feedback),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<ArticleFeedback>;
}

export async function getReadingProfile(): Promise<ReadingProfile> {
  const response = await browserFetch("/api/v1/reading-profile", { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<ReadingProfile>;
}

export async function dismissReadingInsight(key: string): Promise<void> {
  const response = await browserFetch(`/api/v1/reading-profile/insights/${encodeURIComponent(key)}`, { method: "DELETE" });
  if (!response.ok) return apiError(response);
}

export async function updateReadingInsight(key: string, status: "confirmed" | "dismissed"): Promise<ReadingProfile> {
  const response = await browserFetch(`/api/v1/reading-profile/insights/${encodeURIComponent(key)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<ReadingProfile>;
}

export async function saveSoul(markdown: string, artEnabled: boolean): Promise<ReadingProfile> {
  const response = await browserFetch("/api/v1/reading-profile/soul", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ markdown, art_enabled: artEnabled }),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<ReadingProfile>;
}

export async function savePodcastFeedback(podcastId: number, feedback: { rating: ArticleFeedback["rating"]; reasons: PreferenceReason[]; note?: string }): Promise<PreferenceFeedback> {
  const response = await browserFetch(`/api/v1/podcasts/${podcastId}/feedback`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(feedback),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<PreferenceFeedback>;
}

export async function getPodcastFeedback(podcastId: number): Promise<PreferenceFeedback | null> {
  const response = await browserFetch(`/api/v1/podcasts/${podcastId}/feedback`, { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<PreferenceFeedback | null>;
}

export async function saveArtworkFeedback(artworkId: number, feedback: { rating: ArticleFeedback["rating"]; reasons: PreferenceReason[]; note?: string }): Promise<PreferenceFeedback> {
  const response = await browserFetch(`/api/v1/artworks/${artworkId}/feedback`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(feedback),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<PreferenceFeedback>;
}

export async function getArtworkFeedback(artworkId: number): Promise<PreferenceFeedback | null> {
  const response = await browserFetch(`/api/v1/artworks/${artworkId}/feedback`, { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<PreferenceFeedback | null>;
}

export async function getDiscovery(): Promise<DiscoveryStatus> {
  const response = await browserFetch("/api/v1/discovery", { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryStatus>;
}

export async function saveDiscoveryProfile(profile: DiscoveryProfile): Promise<DiscoveryStatus> {
  const response = await browserFetch("/api/v1/discovery/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryStatus>;
}

export async function updateDiscoverySource(
  domain: string,
  status: "active" | "deprioritized" | "excluded",
): Promise<DiscoveryStatus> {
  const response = await browserFetch(`/api/v1/discovery/sources/${encodeURIComponent(domain)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryStatus>;
}

export async function runDiscovery(
  prompt?: string,
  onProgress?: (event: DiscoveryProgressEvent) => void,
): Promise<DiscoveryStatus & { imported: number; recovered?: boolean }> {
  const response = await browserFetch("/api/v1/discovery/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: prompt?.trim() || null }),
  });
  if (!response.ok) return apiError(response);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Die KI-Suche konnte keinen Fortschrittskanal öffnen.");
  const decoder = new TextDecoder();
  let buffer = "";
  let final: (DiscoveryStatus & { imported: number }) | null = null;
  let partialImported = 0;
  let streamError: Error | null = null;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as { type: string; phase?: "articles" | "podcasts"; message?: string; imported?: number; discovery?: DiscoveryStatus; batch?: number; batches?: number; searched?: number; found_count?: number; found?: Article[]; podcasts_found?: number; podcasts?: PodcastEpisode[]; input_tokens?: number; output_tokens?: number; total_tokens?: number };
    if (event.type === "progress") {
      partialImported = Math.max(partialImported, event.found_count ?? 0);
      onProgress?.(event as DiscoveryProgressEvent);
    }
    if (event.type === "error") {
      partialImported = Math.max(partialImported, event.imported ?? 0);
      streamError = new Error(event.message || "Die KI-Suche ist fehlgeschlagen.");
    }
    if (event.type === "status" && event.discovery) final = { imported: event.imported ?? 0, ...event.discovery };
  };
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(consume);
      if (chunk.done) break;
    }
  } catch (error) {
    streamError = error instanceof Error ? error : new Error("Die Netzwerkverbindung zur KI-Suche wurde unterbrochen.");
  }
  if (buffer.trim()) {
    try {
      consume(buffer);
    } catch (error) {
      streamError = error instanceof Error ? error : new Error("Die Netzwerkverbindung zur KI-Suche wurde unterbrochen.");
    }
  }
  if (!final && (streamError || partialImported > 0)) {
    try {
      const recovered = await getDiscovery();
      return { ...recovered, imported: partialImported, recovered: true };
    } catch {
      throw streamError || new Error("Die KI-Suche wurde ohne Abschlussmeldung beendet.");
    }
  }
  if (!final) throw streamError || new Error("Die KI-Suche wurde ohne Abschlussmeldung beendet.");
  return final;
}

export async function getDiscoveryChat(): Promise<DiscoveryChatStatus> {
  const response = await browserFetch("/api/v1/discovery/chat", { cache: "no-store" });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryChatStatus>;
}

export async function sendDiscoveryChat(message: string): Promise<DiscoveryChatStatus> {
  const response = await browserFetch("/api/v1/discovery/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryChatStatus>;
}

export async function researchDiscoveryChat(
  message: string,
  maxArticles: number,
  maxPodcasts: number | null,
  breadth: "focused" | "balanced" | "expansive",
): Promise<DiscoveryChatResearch> {
  const response = await browserFetch("/api/v1/discovery/chat/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, max_articles: maxArticles, max_podcasts: maxPodcasts, breadth }),
  });
  if (!response.ok) return apiError(response);
  return response.json() as Promise<DiscoveryChatResearch>;
}

export async function clearDiscoveryChat(): Promise<void> {
  const response = await browserFetch("/api/v1/discovery/chat", { method: "DELETE" });
  if (!response.ok) return apiError(response);
}
