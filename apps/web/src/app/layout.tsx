import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Silk Export Intelligence",
  description: "AI-powered export intelligence for Saudi manufacturers",
};

// The real <html>/<body> live in the [locale] layout so lang/dir can be set
// per locale. This root just passes children through.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
