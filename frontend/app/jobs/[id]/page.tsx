"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { downloadUrl, getJob, type JobDetail } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

const POLL_MS = 2000;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-5 py-4">
      <dt className="field-label">{label}</dt>
      <dd className="mt-1.5 text-xl font-medium tabular-nums text-telecom">
        {value}
      </dd>
    </div>
  );
}

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
        if (next.status !== "DONE" && next.status !== "FAILED") {
          timer = setTimeout(refresh, POLL_MS);
        }
      } catch (cause) {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "cannot reach the API");
        timer = setTimeout(refresh, POLL_MS);
      }
    }

    void refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [params.id]);

  if (error && !job) return <p className="text-sm text-care">{error}</p>;
  if (!job) return <p className="text-sm font-light text-telecom/50">Loading…</p>;

  const openDisputes = job.discrepancies.filter((d) => d.status === "OPEN");

  return (
    <main>
      <Link
        href="/"
        className="text-sm font-light text-telecom/50 hover:text-digital"
      >
        &larr; All conversions
      </Link>

      <div className="mt-5 flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-telecom">
          {job.filename}
        </h1>
        <StatusBadge status={job.status} />
      </div>

      {job.error && (
        <pre className="mt-6 overflow-x-auto rounded-brand bg-care/10 p-5 text-sm text-care">
          {job.error}
        </pre>
      )}

      <dl className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Pages" value={String(job.page_count)} />
        <Stat label="Cells" value={String(job.cell_count)} />
        <Stat label="Time" value={`${(job.duration_ms / 1000).toFixed(1)}s`} />
        <Stat label="To review" value={String(openDisputes.length)} />
      </dl>

      {job.pages.length > 0 && (
        <section className="mt-10">
          <h2 className="field-label">Pages</h2>
          <div className="panel mt-3 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-light-grey text-left">
                  <th className="px-5 py-3 font-medium text-telecom/60">Page</th>
                  <th className="px-5 py-3 font-medium text-telecom/60">Read as</th>
                  <th className="px-5 py-3 text-right font-medium text-telecom/60">
                    Rows
                  </th>
                  <th className="px-5 py-3 text-right font-medium text-telecom/60">
                    Columns
                  </th>
                </tr>
              </thead>
              <tbody>
                {job.pages.map((page) => (
                  <tr
                    key={page.page_number}
                    className="border-b border-light-grey/60 last:border-0"
                  >
                    <td className="px-5 py-3 text-telecom">{page.page_number}</td>
                    <td className="px-5 py-3 font-light text-telecom/70">
                      {page.kind}
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-telecom/70">
                      {page.n_rows}
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-telecom/70">
                      {page.n_cols}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="mt-10 flex flex-wrap items-center gap-3">
        {job.has_output && (
          <a href={downloadUrl(job.id)} className="btn-primary">
            Download spreadsheet
          </a>
        )}
        {job.pages.length > 0 && (
          <Link href={`/jobs/${job.id}/review`} className="btn-ghost">
            Open review
          </Link>
        )}
        {job.has_verified_output && (
          <a
            href={downloadUrl(job.id, true)}
            className="text-sm font-medium text-digital hover:underline"
          >
            Download corrected version
          </a>
        )}
      </div>
    </main>
  );
}
