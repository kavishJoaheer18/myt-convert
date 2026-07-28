/**
 * The myt wordmark, set per the guidelines: always lowercase, never with a
 * full stop, and given clear space around it. The product name sits beside it
 * as a service descriptor rather than competing with the brand.
 */
export function Wordmark({ tone = "dark" }: { tone?: "dark" | "light" }) {
  const brand = tone === "light" ? "text-white" : "text-telecom";
  const service = tone === "light" ? "text-white/70" : "text-telecom/55";

  return (
    <span className="inline-flex items-baseline gap-2.5 px-1">
      <span className={`text-2xl font-bold lowercase tracking-tight ${brand}`}>
        myt
      </span>
      <span className={`h-4 w-px ${tone === "light" ? "bg-white/30" : "bg-light-grey"}`} />
      <span className={`text-base font-light tracking-tight ${service}`}>
        gridlock
      </span>
    </span>
  );
}
