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
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <section
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
      className={`panel relative overflow-hidden p-10 text-center transition ${
        dragging ? "border-digital ring-2 ring-digital/25" : ""
      }`}
    >
      {/* A slim gradient edge, the guidelines' Digital Blue to Aqua at 0°. */}
      <div className="absolute inset-x-0 top-0 h-1 bg-aqua-gradient" />

      <h2 className="text-lg font-medium text-telecom">Convert a PDF</h2>
      <p className="mx-auto mt-2 max-w-md text-sm font-light text-telecom/60">
        Drop a file here and it comes back as a spreadsheet, with the values in
        the right cells and the fonts, borders and merges of the source.
      </p>

      <label className="mt-7 inline-block">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void submit(file);
          }}
          className="sr-only"
        />
        <span className="btn-primary cursor-pointer">
          {busy ? "Converting…" : "Choose a PDF"}
        </span>
      </label>

      {busy && (
        <p className="mt-4 text-sm font-light text-digital">
          Scanned pages take a little longer — they go through OCR.
        </p>
      )}
      {error && <p className="mt-4 text-sm text-care">{error}</p>}
    </section>
  );
}
