import type { JobStatus } from "@/lib/api";

/**
 * Status colours come from the secondary palette, which the guidelines set
 * aside for differentiating states and services.
 */
const STYLES: Record<JobStatus, string> = {
  QUEUED: "bg-light-grey/50 text-telecom/70",
  PROCESSING: "bg-digital/10 text-digital",
  NEEDS_REVIEW: "bg-care/10 text-care",
  DONE: "bg-money/15 text-money",
  FAILED: "bg-care/15 text-care",
};

const LABELS: Record<JobStatus, string> = {
  QUEUED: "queued",
  PROCESSING: "converting",
  NEEDS_REVIEW: "needs review",
  DONE: "done",
  FAILED: "failed",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
