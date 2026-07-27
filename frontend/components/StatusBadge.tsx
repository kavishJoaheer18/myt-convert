import type { JobStatus } from "@/lib/api";

const STYLES: Record<JobStatus, string> = {
  QUEUED: "bg-neutral-800 text-neutral-300",
  PROCESSING: "bg-sky-950 text-sky-300",
  NEEDS_REVIEW: "bg-amber-950 text-amber-300",
  DONE: "bg-emerald-950 text-emerald-300",
  FAILED: "bg-red-950 text-red-300",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {status.replace("_", " ").toLowerCase()}
    </span>
  );
}
