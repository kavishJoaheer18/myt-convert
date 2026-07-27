"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { downloadUrl, listJobs, type JobSummary } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

//: Conversions finish in seconds, so a short poll keeps the list honest.
const POLL_MS = 2000;

export function JobList() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const next = await listJobs();
        if (active) {
          setJobs(next);
          setError(null);
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : "cannot reach API");
        }
      }
    }

    void refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return <p className="mt-8 text-sm text-red-400">{error}</p>;
  }

  if (jobs === null) {
    return <p className="mt-8 text-sm text-neutral-500">Loading jobs…</p>;
  }

  if (jobs.length === 0) {
    return (
      <p className="mt-8 text-sm text-neutral-500">
        No conversions yet. Upload a PDF to get started.
      </p>
    );
  }

  return (
    <table className="mt-8 w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-neutral-800 text-left text-neutral-500">
          <th className="py-2 font-medium">File</th>
          <th className="py-2 font-medium">Status</th>
          <th className="py-2 text-right font-medium">Pages</th>
          <th className="py-2 text-right font-medium">Cells</th>
          <th className="py-2 text-right font-medium">Result</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id} className="border-b border-neutral-900">
            <td className="py-3">
              <Link
                href={`/jobs/${job.id}`}
                className="text-neutral-200 hover:text-emerald-400"
              >
                {job.filename}
              </Link>
            </td>
            <td className="py-3">
              <StatusBadge status={job.status} />
            </td>
            <td className="py-3 text-right tabular-nums text-neutral-400">
              {job.page_count}
            </td>
            <td className="py-3 text-right tabular-nums text-neutral-400">
              {job.cell_count}
            </td>
            <td className="py-3 text-right">
              {job.status === "DONE" || job.status === "NEEDS_REVIEW" ? (
                <a
                  href={downloadUrl(job.id)}
                  className="text-emerald-400 hover:underline"
                >
                  Download .xlsx
                </a>
              ) : (
                <span className="text-neutral-600">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
