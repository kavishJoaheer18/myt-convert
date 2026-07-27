"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { downloadUrl, getJob, type JobDetail } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

const POLL_MS = 2000;

export default function JobPage({ params }: { params: { id: string } }) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      try {
        const next = await getJob(params.id);
        if (!active) return;
        setJob(next);
        setError(null);
        // Stop polling once the job reaches a terminal state.
        if (next.status !== "DONE" && next.status !== "FAILED") {
          timer = setTimeout(refresh, POLL_MS);
        }
      } catch (cause) {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "cannot reach API");
        timer = setTimeout(refresh, POLL_MS);
      }
    }

    void refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [params.id]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!job) return <p className="text-sm text-neutral-500">Loading…</p>;

  return (
    <main>
      <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-300">
        &larr; All jobs
      </Link>

      <div className="mt-4 flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{job.filename}</h1>
        <StatusBadge status={job.status} />
      </div>

      {job.error && (
        <pre className="mt-6 overflow-x-auto rounded border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {job.error}
        </pre>
      )}

      <dl className="mt-8 grid grid-cols-2 gap-6 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-neutral-500">Pages</dt>
          <dd className="mt-1 tabular-nums">{job.page_count}</dd>
        </div>
        <div>
          <dt className="text-neutral-500">Cells</dt>
          <dd className="mt-1 tabular-nums">{job.cell_count}</dd>
        </div>
        <div>
          <dt className="text-neutral-500">Duration</dt>
          <dd className="mt-1 tabular-nums">
            {(job.duration_ms / 1000).toFixed(2)}s
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">Job</dt>
          <dd className="mt-1 font-mono text-xs text-neutral-400">{job.id}</dd>
        </div>
      </dl>

      {job.pages.length > 0 && (
        <table className="mt-10 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-neutral-500">
              <th className="py-2 font-medium">Page</th>
              <th className="py-2 font-medium">Source</th>
              <th className="py-2 text-right font-medium">Rows</th>
              <th className="py-2 text-right font-medium">Columns</th>
            </tr>
          </thead>
          <tbody>
            {job.pages.map((page) => (
              <tr key={page.page_number} className="border-b border-neutral-900">
                <td className="py-2">{page.page_number}</td>
                <td className="py-2 text-neutral-400">{page.kind}</td>
                <td className="py-2 text-right tabular-nums">{page.n_rows}</td>
                <td className="py-2 text-right tabular-nums">{page.n_cols}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {job.has_output && (
        <a
          href={downloadUrl(job.id)}
          className="mt-10 inline-block rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Download .xlsx
        </a>
      )}
    </main>
  );
}
