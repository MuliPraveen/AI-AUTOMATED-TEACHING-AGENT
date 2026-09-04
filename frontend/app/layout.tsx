import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Automated Teaching Agent",
  description: "Multi-agent RAG teaching platform with a synchronized talking avatar",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body className="min-h-screen antialiased">{children}</body></html>;
}
