/** Typed client for the GridLock API. */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export interface JobDetail extends JobSummary {
  error: string | null;
  duration_ms: number;
  has_output: boolean;
  has_verified_output: boolean;
  pages: PageSummary[];
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
