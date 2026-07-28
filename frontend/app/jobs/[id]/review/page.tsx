"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SheetTable } from "@/components/SheetTable";
import {
  cropUrl,
  downloadUrl,
  getJob,
  getSheet,
  pageImageUrl,
  submitReview,
  type CellCorrection,
  type JobDetail,
  type Sheet,
  type SheetCell,
} from "@/lib/api";

export default function ReviewPage({ params }: { params: { id: string } }) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [page, setPage] = useState(1);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getJob(params.id)
      .then((next) => active && setJob(next))
      .catch((cause) => active && setError(String(cause)));
    return () => {
      active = false;
    };
  }, [params.id]);

  useEffect(() => {
    let active = true;
    setSheet(null);
    getSheet(params.id, page)
      .then((next) => active && setSheet(next))
      .catch((cause) => active && setError(String(cause)));
    return () => {
      active = false;
    };
  }, [params.id, page]);

  // Editing a cell on one page must not carry over to another.
  useEffect(() => setEdits({}), [page]);

  const openOnThisPage = useMemo(
    () =>
      (job?.discrepancies ?? []).filter(
        (d) => d.page_number === page && d.status === "OPEN",
      ),
    [job, page],
  );

  const disputed = useMemo(
    () => new Set(openOnThisPage.map((d) => `${d.row}:${d.col}`)),
    [openOnThisPage],
  );

  const onEdit = useCallback((cell: SheetCell, value: string) => {
    setEdits((current) => {
      const key = `${cell.row}:${cell.col}`;
      if (value === cell.text) {
        // Reverting an edit should leave no trace of it.
        const { [key]: _discarded, ...rest } = current;
        return rest;
      }
      return { ...current, [key]: value };
    });
  }, []);

  async function save(acceptRemaining: boolean) {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const corrections: CellCorrection[] = Object.entries(edits).map(
        ([key, value]) => {
          const [row, col] = key.split(":").map(Number);
          return { page_number: page, row, col, value };
        },
      );
      const response = await submitReview(params.id, corrections, acceptRemaining);
      setSaved(
        `Applied ${response.applied} correction${response.applied === 1 ? "" : "s"}; ` +
          `${response.remaining_discrepancies} left to review.`,
      );
      setEdits({});
      setJob(await getJob(params.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not save review");
    } finally {
      setBusy(false);
    }
  }

  if (error && !job) return <p className="text-sm text-red-400">{error}</p>;
  if (!job) return <p className="text-sm text-neutral-500">Loading…</p>;

  const editCount = Object.keys(edits).length;

  return (
    <main>
      <Link
        href={`/jobs/${params.id}`}
        className="text-sm text-neutral-500 hover:text-neutral-300"
      >
        &larr; Back to job
      </Link>

      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        Review {job.filename}
      </h1>
      <p className="mt-1 text-sm text-neutral-500">
        Click any cell to correct it. Amber cells are the ones the second reading
        disagreed about; blue cells were read with lower confidence.
      </p>

      {job.pages.length > 1 && (
        <div className="mt-6 flex gap-2">
          {job.pages.map((p) => (
            <button
              key={p.page_number}
              onClick={() => setPage(p.page_number)}
              className={`rounded px-3 py-1 text-sm ${
                p.page_number === page
                  ? "bg-emerald-600 text-white"
                  : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700"
              }`}
            >
              Page {p.page_number}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-2 text-sm font-medium text-neutral-400">Source page</h2>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={pageImageUrl(params.id, page)}
            alt={`Page ${page} of ${job.filename}`}
            className="w-full rounded border border-neutral-800 bg-white"
          />
        </section>

        <section>
          <h2 className="mb-2 text-sm font-medium text-neutral-400">
            Generated sheet
          </h2>
          {sheet ? (
            <SheetTable
              sheet={sheet}
              edits={edits}
              disputed={disputed}
              onEdit={onEdit}
            />
          ) : (
            <p className="text-sm text-neutral-500">Loading sheet…</p>
          )}
        </section>
      </div>

      {openOnThisPage.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-sm font-medium text-neutral-400">
            Disputed cells on this page
          </h2>
          <ul className="space-y-3">
            {openOnThisPage.map((d) => (
              <li
                key={d.id}
                className="flex items-center gap-4 rounded border border-neutral-800 p-3 text-sm"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={cropUrl(params.id, d.id)}
                  alt={`Crop of row ${d.row + 1}, column ${d.col + 1}`}
                  className="h-10 rounded bg-white"
                />
                <span className="font-mono text-neutral-500">
                  r{d.row + 1}c{d.col + 1}
                </span>
                <span>
                  extracted{" "}
                  <span className="font-mono text-amber-300">
                    {d.deterministic_value || "(empty)"}
                  </span>
                </span>
                <span>
                  second reading{" "}
                  <span className="font-mono text-sky-300">{d.vlm_value}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-10 flex items-center gap-4">
        <button
          disabled={busy || editCount === 0}
          onClick={() => void save(false)}
          className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          Save {editCount} correction{editCount === 1 ? "" : "s"}
        </button>
        <button
          disabled={busy}
          onClick={() => void save(true)}
          className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
        >
          Save and accept the rest
        </button>
        {job.has_verified_output && (
          <a
            href={downloadUrl(params.id, true)}
            className="text-sm text-emerald-400 hover:underline"
          >
            Download verified .xlsx
          </a>
        )}
      </div>

      {saved && <p className="mt-4 text-sm text-emerald-400">{saved}</p>}
      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
    </main>
  );
}
