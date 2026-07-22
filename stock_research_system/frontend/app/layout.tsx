import { Inter } from "next/font/google";
import type { Metadata } from "next";

import { AppProviders } from "@/providers/AppProviders";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "FinQuest",
  description: "FinQuest: an adaptive financial-education platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
