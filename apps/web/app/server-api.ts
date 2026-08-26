import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { Article, DiscoveryChatStatus, DiscoveryStatus, Home, PodcastEpisode, ReadingProfile, SetupStatus } from "./types";

const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";

async function serverFetch(path: string): Promise<Response> {
  const token = (await cookies()).get("derive_session")?.value;
  const response = await fetch(`${apiUrl}${path}`, {
    cache: "no-store",
    headers: token ? { "X-Derive-Session": token } : {},
  });
  if (response.status === 401) redirect("/login?expired=1");
  if (!response.ok) throw new Error(`dérive API returned ${response.status}.`);
  return response;
}

export async function getHome(): Promise<Home> { return (await serverFetch("/api/v1/home")).json(); }
export async function getSetup(): Promise<SetupStatus> { return (await serverFetch("/api/v1/setup")).json(); }
export async function getArticle(id: string): Promise<Article> { return (await serverFetch(`/api/v1/articles/${id}`)).json(); }
export async function getArticles(): Promise<Article[]> { return (await serverFetch("/api/v1/articles")).json(); }
export async function getPodcasts(): Promise<PodcastEpisode[]> { return (await serverFetch("/api/v1/podcasts")).json(); }
export async function getPodcast(id: string): Promise<PodcastEpisode> { return (await serverFetch(`/api/v1/podcasts/${id}`)).json(); }
export async function getDiscovery(): Promise<DiscoveryStatus> { return (await serverFetch("/api/v1/discovery")).json(); }
export async function getDiscoveryChat(): Promise<DiscoveryChatStatus> { return (await serverFetch("/api/v1/discovery/chat")).json(); }
export async function getReadingProfile(): Promise<ReadingProfile> { return (await serverFetch("/api/v1/reading-profile")).json(); }
