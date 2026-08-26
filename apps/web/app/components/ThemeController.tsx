"use client";

import { useEffect } from "react";

export function ThemeController() {
  useEffect(() => {
    // SetupWizard applies the persisted server preference while its form is mounted.
    // Do not let a stale localStorage value overwrite the first-run selection.
    if (document.querySelector(".setup-shell")) return;
    const preference = localStorage.getItem("reado-theme") ?? "system";
    const apply = () => {
      const resolved = preference === "system"
        ? window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
        : preference;
      document.documentElement.dataset.theme = resolved;
      window.dispatchEvent(new CustomEvent("reado-theme-change", { detail: resolved }));
    };
    apply();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);
  return null;
}
