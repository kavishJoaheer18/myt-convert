"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { uploadPdf } from "@/lib/api";

export function UploadForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function submit(file: File) {
    setBusy(true);
    setError(null);
    try {
      await uploadPdf(file);
      // The job starts QUEUED; the list polls until the worker finishes.
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <section>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void submit(file);
        }}
        className={`rounded-lg border border-dashed p-10 text-center transition ${
          dragging
            ? "border-emerald-500 bg-emerald-950/20"
            : "border-neutral-700 bg-neutral-900/40"
        }`}
      >
        <p className="mb-4 text-sm text-neutral-400">
          Drop a PDF here, or choose one to convert.
        </p>

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void submit(file);
          }}
          className="block w-full text-sm text-neutral-400 file:mr-4 file:rounded file:border-0 file:bg-emerald-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-emerald-500 disabled:opacity-50"
        />

        {busy && (
          <p className="mt-4 text-sm text-sky-400">Uploading and queueing…</p>
        )}
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
      </div>
    </section>
  );
}
