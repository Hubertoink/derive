import type { Metadata } from "next";

import { ThemeController } from "./components/ThemeController";
import "./globals.css";

export const metadata: Metadata = {
  title: "dérive — Dein Leseraum",
  description: "Eine ruhige, kuratierte Umgebung für Texte, die es wert sind gelesen zu werden.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body><ThemeController />{children}</body>
    </html>
  );
}

