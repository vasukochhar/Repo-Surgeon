import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Repo Surgeon",
  description: "Autonomous codebase modernization: plan, edit, verify, and open pull requests, unattended.",
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%A9%BA%3C/text%3E%3C/svg%3E",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface-glass)] backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <span aria-hidden="true" className="dot-live h-2 w-2 shrink-0" />
              <span className="font-mono text-sm font-medium tracking-tight text-[var(--text)]">
                REPO SURGEON
              </span>
            </Link>
            <span className="eyebrow hidden sm:inline">Autonomous codebase surgery</span>
          </div>
        </header>
        <div className="rise-in flex flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
