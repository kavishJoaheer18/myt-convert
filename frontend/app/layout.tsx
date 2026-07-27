import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "GridLock",
  description: "Layout-faithful PDF to Excel conversion",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto max-w-5xl px-6 py-10">
          <header className="mb-10 flex items-baseline justify-between border-b border-neutral-800 pb-4">
            <Link href="/" className="text-xl font-semibold tracking-tight">
              Grid<span className="text-emerald-400">Lock</span>
            </Link>
            <p className="text-sm text-neutral-500">
              PDF &rarr; Excel, layout intact
            </p>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
