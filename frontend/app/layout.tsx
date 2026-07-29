import type { Metadata } from "next";
import { Poppins } from "next/font/google";
import Link from "next/link";
import { Wordmark } from "@/components/Wordmark";
import "./globals.css";

// Primary weights per the guidelines: Light, Medium, Bold.
const poppins = Poppins({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
});

export const metadata: Metadata = {
  title: "myt convert",
  description: "Layout-faithful PDF to Excel conversion",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={poppins.variable}>
      <body>
        <header className="border-b border-light-grey bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
            <Link href="/" aria-label="myt convert home">
              <Wordmark />
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              <Link
                href="/"
                className="rounded-brand px-4 py-2 font-light text-telecom/70 transition hover:bg-digital/5 hover:text-digital"
              >
                Convert
              </Link>
              <Link
                href="/quotes"
                className="rounded-brand px-4 py-2 font-light text-telecom/70 transition hover:bg-digital/5 hover:text-digital"
              >
                Supplier quotes
              </Link>
            </nav>
          </div>
        </header>

        <div className="mx-auto max-w-6xl px-6 py-10">{children}</div>

        <footer className="mx-auto max-w-6xl px-6 pb-10 pt-4">
          <p className="text-xs font-light text-telecom/40">
            A Mauritius Telecom service.
          </p>
        </footer>
      </body>
    </html>
  );
}
