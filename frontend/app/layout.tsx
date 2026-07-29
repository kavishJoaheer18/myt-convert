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
            <p className="hidden text-sm font-light text-telecom/55 sm:block">
              PDF to Excel, layout intact
            </p>
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
