"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import { researchDiscoveryChat, runDiscovery, sendDiscoveryChat } from "../api";
import { DiscoveryChatResearch, DiscoveryChatStatus, DiscoveryProgressEvent, DiscoveryStatus } from "../types";

export type BackgroundOperationKind = "search" | "research" | "chat";

export type BackgroundOperation = {
  id: string;
  kind: BackgroundOperationKind;
  label: string;
  startedAt: number;
};

type BackgroundOperationsContextValue = {
  operations: BackgroundOperation[];
  startDiscovery: (
    prompt?: string,
    onProgress?: (event: DiscoveryProgressEvent) => void,
  ) => Promise<DiscoveryStatus & { imported: number; recovered?: boolean }>;
  startResearch: (
    message: string,
    maxArticles: number,
    maxPodcasts: number | null,
    breadth: "focused" | "balanced" | "expansive",
  ) => Promise<DiscoveryChatResearch>;
  startChat: (message: string) => Promise<DiscoveryChatStatus>;
  cancelOperation: (id: string) => void;
};

const BackgroundOperationsContext = createContext<BackgroundOperationsContextValue | null>(null);

export function BackgroundOperationsProvider({ children }: { children: React.ReactNode }) {
  const [operations, setOperations] = useState<BackgroundOperation[]>([]);
  const controllers = useRef(new Map<string, AbortController>());
  const sequence = useRef(0);

  const track = useCallback(<T,>(kind: BackgroundOperationKind, label: string, task: (signal: AbortSignal) => Promise<T>) => {
    const id = `${Date.now()}-${sequence.current++}`;
    const controller = new AbortController();
    controllers.current.set(id, controller);
    setOperations((current) => [...current, { id, kind, label, startedAt: Date.now() }]);
    return task(controller.signal).finally(() => {
      controllers.current.delete(id);
      setOperations((current) => current.filter((operation) => operation.id !== id));
    });
  }, []);

  const startDiscovery = useCallback((prompt?: string, onProgress?: (event: DiscoveryProgressEvent) => void) => (
    track("search", "KI-Suche", (signal) => runDiscovery(prompt, onProgress, signal))
  ), [track]);

  const startResearch = useCallback((message: string, maxArticles: number, maxPodcasts: number | null, breadth: "focused" | "balanced" | "expansive") => (
    track("research", "Recherche", (signal) => researchDiscoveryChat(message, maxArticles, maxPodcasts, breadth, signal))
  ), [track]);

  const startChat = useCallback((message: string) => (
    track("chat", "Chat", (signal) => sendDiscoveryChat(message, signal))
  ), [track]);

  const cancelOperation = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
  }, []);

  const value = useMemo(() => ({
    operations,
    startDiscovery,
    startResearch,
    startChat,
    cancelOperation,
  }), [operations, startDiscovery, startResearch, startChat, cancelOperation]);

  return <BackgroundOperationsContext.Provider value={value}>{children}</BackgroundOperationsContext.Provider>;
}

export function useBackgroundOperations() {
  const context = useContext(BackgroundOperationsContext);
  if (!context) throw new Error("useBackgroundOperations must be used within BackgroundOperationsProvider");
  return context;
}
