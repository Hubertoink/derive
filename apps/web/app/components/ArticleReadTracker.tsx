"use client";

import { useEffect } from "react";

export function ArticleReadTracker({ articleId, isRead }: { articleId: number; isRead: boolean }) {
  useEffect(() => {
    if (isRead) return;
    void fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/articles/${articleId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ is_read: true }),
    }).then((response) => {
      if (response.ok) window.dispatchEvent(new CustomEvent("reado:article-read", { detail: articleId }));
    });
  }, [articleId, isRead]);

  return null;
}
