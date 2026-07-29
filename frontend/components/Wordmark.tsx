import { MytLogo } from "./MytLogo";

/**
 * The myt wordmark with the service name beside it.
 *
 * "Service and product names should follow the same naming structure", which
 * the guidelines illustrate as myt money, myt care, myt traffic — always
 * lowercase, and never MYT, MyT or my.t.
 */
export function Wordmark({
  tone = "dark",
  className = "",
}: {
  tone?: "dark" | "light";
  className?: string;
}) {
  const brand = tone === "light" ? "text-white" : "text-myt";
  const service = tone === "light" ? "text-white/70" : "text-telecom/55";
  const rule = tone === "light" ? "bg-white/30" : "bg-light-grey";

  return (
    <span className={`inline-flex items-center gap-3 ${className}`}>
      <MytLogo className={`h-6 w-auto ${brand}`} />
      <span className={`h-4 w-px ${rule}`} aria-hidden />
      <span className={`text-base font-light lowercase tracking-tight ${service}`}>
        convert
      </span>
    </span>
  );
}
