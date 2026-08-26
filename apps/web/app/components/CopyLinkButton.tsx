"use client";

import { IconCheck, IconCopy } from "@tabler/icons-react";
import { useState } from "react";

export function CopyLinkButton({ url, compact = false, hover = false }: { url: string; compact?: boolean; hover?: boolean }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("Link kopieren:", url);
    }
  }

  const label = copied ? "Link kopiert" : "Link kopieren";
  return (
    <button className={`copy-link copy-link--icon${compact ? " copy-link--compact" : ""}${hover ? " copy-link--hover" : ""}`} type="button" onClick={copy} aria-label={label} title={label}>
      {copied ? "Kopiert ✓" : "Link kopieren"}
      {copied ? <IconCheck size={16} stroke={2} aria-hidden="true" /> : <IconCopy size={16} stroke={1.8} aria-hidden="true" />}
    </button>
  );
}
