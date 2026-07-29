"use client";

import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import {
  listQuoteBatches,
  quoteDownloadUrl,
  uploadQuotes,
  type QuoteBatch,
} from "@/lib/api";

const POLL_MS = 2500;

export default function QuotesPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [batches, setBatches] = useState<QuoteBatch[] | null>(null);
  const [selected, setSelected] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const next = await listQuoteBatches();
        if (active) setBatches(next);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  function addFiles(incoming: FileList | null) {
    if (!incoming) return;
    const pdfs = Array.from(incoming).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf"),
    );
    setSelected((current) => [...current, ...pdfs]);
    setError(pdfs.length < (incoming?.length ?? 0) ? "Only PDFs can be read." : null);
  }

  async function submit() {
    if (selected.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await uploadQuotes(selected);
      setSelected([]);
      if (inputRef.current) inputRef.current.value = "";
      setBatches(await listQuoteBatches());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1 className="text-2xl font-bold tracking-tight text-telecom">
        Supplier quotes
      </h1>
      <p className="mt-2 max-w-2xl text-sm font-light text-telecom/60">
        Drop in quotes from any supplier. Every line item comes back in one
        spreadsheet, in your standard format — date, supplier, code,
        description, currency, quantity, price, discount and total.
      </p>

      <section
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
        className={`panel relative mt-8 overflow-hidden p-8 transition ${
          dragging ? "border-digital ring-2 ring-digital/25" : ""
        }`}
      >
        <div className="absolute inset-x-0 top-0 h-1 bg-aqua-gradient" />

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-medium text-telecom">
              Add quote PDFs
            </h2>
            <p className="mt-1 text-sm font-light text-telecom/55">
              One file or many — they are combined into a single sheet.
            </p>
          </div>

          <label>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              multiple
              disabled={busy}
              onChange={(event) => addFiles(event.target.files)}
              className="sr-only"
            />
            <span className="btn-ghost cursor-pointer">Choose files</span>
          </label>
        </div>

        {selected.length > 0 && (
          <>
            <ul className="mt-6 space-y-1.5">
              {selected.map((file, index) => (
                <li
                  key={`${file.name}-${index}`}
                  className="flex items-center justify-between rounded border border-light-grey px-3 py-2 text-sm"
                >
                  <span className="truncate text-telecom">{file.name}</span>
                  <button
                    onClick={() =>
                      setSelected((c) => c.filter((_, i) => i !== index))
                    }
                    className="ml-4 shrink-0 text-xs text-telecom/45 hover:text-care"
                  >
                    remove
                  </button>
                </li>
              ))}
            </ul>

            <button
              disabled={busy}
              onClick={() => void submit()}
              className="btn-primary mt-5"
            >
              {busy
                ? "Reading…"
                : `Extract ${selected.length} quote${selected.length === 1 ? "" : "s"}`}
            </button>
          </>
        )}

        {error && <p className="mt-4 text-sm text-care">{error}</p>}
      </section>

      {batches !== null && batches.length > 0 && (
        <section className="mt-12">
          <h2 className="field-label">Batches</h2>
          <div className="panel mt-3 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-light-grey text-left">
                  <th className="px-5 py-3 font-medium text-telecom/60">Files</th>
                  <th className="px-5 py-3 font-medium text-telecom/60">Status</th>
                  <th className="px-5 py-3 text-right font-medium text-telecom/60">
                    Line items
                  </th>
                  <th className="px-5 py-3 text-right font-medium text-telecom/60" />
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr
                    key={batch.id}
                    className="border-b border-light-grey/60 align-top last:border-0"
                  >
                    <td className="px-5 py-3.5">
                      <span className="text-telecom">
                        {batch.filenames[0] ?? `${batch.file_count} files`}
                        {batch.file_count > 1 && (
                          <span className="text-telecom/50">
                            {" "}
                            +{batch.file_count - 1} more
                          </span>
                        )}
                      </span>
                      {batch.warnings.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5">
                          {batch.warnings.slice(0, 3).map((warning) => (
                            <li key={warning} className="text-xs text-care">
                              {warning}
                            </li>
                          ))}
                        </ul>
                      )}
                      {batch.error && (
                        <p className="mt-1.5 text-xs text-care">{batch.error}</p>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={batch.status} />
                    </td>
                    <td className="px-5 py-3.5 text-right tabular-nums text-telecom/70">
                      {batch.row_count}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      {batch.has_output ? (
                        <a
                          href={quoteDownloadUrl(batch.id)}
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
      )}
    </main>
  );
}
