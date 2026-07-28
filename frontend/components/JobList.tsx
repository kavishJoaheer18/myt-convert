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
          setError(cause instanceof Error ? cause.message : "cannot reach the API");
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
    return (
      <p className="mt-10 rounded-brand bg-care/10 px-4 py-3 text-sm text-care">
        {error}
      </p>
    );
  }

  if (jobs === null) {
    return <p className="mt-10 text-sm font-light text-telecom/50">Loading…</p>;
  }

  if (jobs.length === 0) {
    return (
      <p className="mt-10 text-sm font-light text-telecom/50">
        No conversions yet.
      </p>
    );
  }

  return (
    <section className="mt-12">
      <h2 className="field-label">Conversions</h2>

      <div className="panel mt-3 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-light-grey text-left">
              <th className="px-5 py-3 font-medium text-telecom/60">File</th>
              <th className="px-5 py-3 font-medium text-telecom/60">Status</th>
              <th className="px-5 py-3 text-right font-medium text-telecom/60">
                Pages
              </th>
              <th className="px-5 py-3 text-right font-medium text-telecom/60">
                Cells
              </th>
              <th className="px-5 py-3 text-right font-medium text-telecom/60" />
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr
                key={job.id}
                className="border-b border-light-grey/60 last:border-0 hover:bg-digital/[0.03]"
              >
                <td className="px-5 py-3.5">
                  <Link
                    href={`/jobs/${job.id}`}
                    className="font-medium text-telecom hover:text-digital"
                  >
                    {job.filename}
                  </Link>
                </td>
                <td className="px-5 py-3.5">
                  <StatusBadge status={job.status} />
                </td>
                <td className="px-5 py-3.5 text-right font-light tabular-nums text-telecom/70">
                  {job.page_count}
                </td>
                <td className="px-5 py-3.5 text-right font-light tabular-nums text-telecom/70">
                  {job.cell_count}
                </td>
                <td className="px-5 py-3.5 text-right">
                  {job.status === "DONE" || job.status === "NEEDS_REVIEW" ? (
                    <a
                      href={downloadUrl(job.id)}
                      className="font-medium text-digital hover:underline"
                    >
                      Download
                    </a>
                  ) : (
                    <span className="text-light-grey">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
