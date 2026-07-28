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
        `Saved ${response.applied} correction${response.applied === 1 ? "" : "s"}. ` +
          `${response.remaining_discrepancies} left to review.`,
      );
      setEdits({});
      setJob(await getJob(params.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not save");
    } finally {
      setBusy(false);
    }
  }

  if (error && !job) return <p className="text-sm text-care">{error}</p>;
  if (!job) return <p className="text-sm font-light text-telecom/50">Loading…</p>;

  const editCount = Object.keys(edits).length;

  return (
    <main>
      <Link
        href={`/jobs/${params.id}`}
        className="text-sm font-light text-telecom/50 hover:text-digital"
      >
        &larr; Back to conversion
      </Link>

      <h1 className="mt-5 text-2xl font-bold tracking-tight text-telecom">
        Review {job.filename}
      </h1>
      <p className="mt-2 max-w-2xl text-sm font-light text-telecom/60">
        Click any cell to correct it. Pink cells are the ones the second reading
        disagreed about; aqua cells were read with lower confidence.
      </p>

      {job.pages.length > 1 && (
        <div className="mt-6 flex flex-wrap gap-2">
          {job.pages.map((p) => (
            <button
              key={p.page_number}
              onClick={() => setPage(p.page_number)}
              className={`rounded-brand px-4 py-1.5 text-sm font-medium transition ${
                p.page_number === page
                  ? "bg-digital text-white"
                  : "border border-light-grey bg-white text-telecom/70 hover:border-digital hover:text-digital"
              }`}
            >
              {p.page_number}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section>
          <h2 className="field-label mb-2">Source page</h2>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={pageImageUrl(params.id, page)}
            alt={`Page ${page} of ${job.filename}`}
            className="panel w-full bg-white"
          />
        </section>

        <section>
          <h2 className="field-label mb-2">Generated sheet</h2>
          {sheet ? (
            <SheetTable
              sheet={sheet}
              edits={edits}
              disputed={disputed}
              onEdit={onEdit}
            />
          ) : (
            <p className="text-sm font-light text-telecom/50">Loading sheet…</p>
          )}
        </section>
      </div>

      {openOnThisPage.length > 0 && (
        <section className="mt-10">
          <h2 className="field-label">Disputed cells</h2>
          <ul className="mt-3 space-y-3">
            {openOnThisPage.map((d) => (
              <li key={d.id} className="panel flex flex-wrap items-center gap-4 p-4 text-sm">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={cropUrl(params.id, d.id)}
                  alt={`Crop of row ${d.row + 1}, column ${d.col + 1}`}
                  className="h-10 rounded border border-light-grey bg-white"
                />
                <span className="font-mono text-xs text-telecom/45">
                  r{d.row + 1}c{d.col + 1}
                </span>
                <span className="font-light text-telecom/70">
                  extracted{" "}
                  <span className="font-medium text-care">
                    {d.deterministic_value || "(empty)"}
                  </span>
                </span>
                <span className="font-light text-telecom/70">
                  second reading{" "}
                  <span className="font-medium text-digital">{d.vlm_value}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-10 flex flex-wrap items-center gap-3">
        <button
          disabled={busy || editCount === 0}
          onClick={() => void save(false)}
          className="btn-primary"
        >
          Save {editCount} correction{editCount === 1 ? "" : "s"}
        </button>
        <button
          disabled={busy}
          onClick={() => void save(true)}
          className="btn-ghost"
        >
          Save and accept the rest
        </button>
        {job.has_verified_output && (
          <a
            href={downloadUrl(params.id, true)}
            className="text-sm font-medium text-digital hover:underline"
          >
            Download corrected spreadsheet
          </a>
        )}
      </div>

      {saved && <p className="mt-4 text-sm text-money">{saved}</p>}
      {error && <p className="mt-4 text-sm text-care">{error}</p>}
    </main>
  );
}
