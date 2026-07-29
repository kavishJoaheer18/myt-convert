/** Typed client for the GridLock API. */

/**
 * Same-origin by default: `/api` is rewritten to the backend server-side (see
 * next.config.mjs). Keeping this relative means the built image carries no
 * hard-coded hostname and runs unchanged on any domain.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type JobStatus =
  | "QUEUED"
  | "PROCESSING"
  | "NEEDS_REVIEW"
  | "DONE"
  | "FAILED";

export interface JobSummary {
  id: string;
  filename: string;
  status: JobStatus;
  page_count: number;
  cell_count: number;
  created_at: string;
  updated_at: string;
}

export interface PageSummary {
  page_number: number;
  kind: string;
  n_rows: number;
  n_cols: number;
  width_pt: number;
  height_pt: number;
}

export interface Discrepancy {
  id: string;
  page_number: number;
  row: number;
  col: number;
  deterministic_value: string;
  vlm_value: string;
  resolved_value: string | null;
  status: "OPEN" | "RESOLVED" | "DISMISSED";
  confidence: number;
}

export interface JobDetail extends JobSummary {
  error: string | null;
  duration_ms: number;
  has_output: boolean;
  has_verified_output: boolean;
  pages: PageSummary[];
  discrepancies: Discrepancy[];
}

export interface SheetCell {
  row: number;
  col: number;
  row_span: number;
  col_span: number;
  text: string;
  number_format: string;
  source: string;
  confidence: number;
}

export interface Sheet {
  page_number: number;
  n_rows: number;
  n_cols: number;
  cells: SheetCell[];
}

export interface CellCorrection {
  page_number: number;
  row: number;
  col: number;
  value: string;
}

export interface ReviewResponse {
  job_id: string;
  status: JobStatus;
  applied: number;
  remaining_discrepancies: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
  });

  if (!response.ok) {
    // FastAPI reports failures as {"detail": "..."}; surface that verbatim.
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => null);
    throw new Error(detail ?? `${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
}

export function listJobs(): Promise<JobSummary[]> {
  return request<JobSummary[]>("/jobs");
}

export function getJob(id: string): Promise<JobDetail> {
  return request<JobDetail>(`/jobs/${id}`);
}

export function uploadPdf(file: File): Promise<{ id: string; status: JobStatus }> {
  const body = new FormData();
  body.append("file", file);
  return request<{ id: string; status: JobStatus }>("/jobs", {
    method: "POST",
    body,
  });
}

export function downloadUrl(id: string, verified = false): string {
  return `${API_URL}/jobs/${id}/download${verified ? "?verified=true" : ""}`;
}

export function getSheet(id: string, pageNumber: number): Promise<Sheet> {
  return request<Sheet>(`/jobs/${id}/sheets/${pageNumber}`);
}

export function pageImageUrl(id: string, pageNumber: number): string {
  return `${API_URL}/jobs/${id}/pages/${pageNumber}/image`;
}

export function cropUrl(id: string, discrepancyId: string): string {
  return `${API_URL}/jobs/${id}/discrepancies/${discrepancyId}/crop`;
}

export function submitReview(
  id: string,
  corrections: CellCorrection[],
  acceptRemaining = false,
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/jobs/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      corrections,
      accept_remaining: acceptRemaining,
    }),
  });
}
