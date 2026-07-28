"use client";

import { useState } from "react";
import type { Sheet, SheetCell } from "@/lib/api";

const CONFIDENCE_WARN = 0.9;

function cellKey(row: number, col: number): string {
  return `${row}:${col}`;
}

function columnLabel(index: number): string {
  let label = "";
  let n = index;
  do {
    label = String.fromCharCode(65 + (n % 26)) + label;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return label;
}

export function SheetTable({
  sheet,
  edits,
  disputed,
  onEdit,
}: {
  sheet: Sheet;
  edits: Record<string, string>;
  /** Cells consensus could not settle, keyed as "row:col". */
  disputed: Set<string>;
  onEdit: (cell: SheetCell, value: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  const byPosition = new Map<string, SheetCell>();
  for (const cell of sheet.cells) {
    byPosition.set(cellKey(cell.row, cell.col), cell);
  }
  // A merged range is drawn once, at its anchor; the covered slots are skipped.
  const covered = new Set<string>();
  for (const cell of sheet.cells) {
    for (let r = cell.row; r < cell.row + cell.row_span; r += 1) {
      for (let c = cell.col; c < cell.col + cell.col_span; c += 1) {
        if (r !== cell.row || c !== cell.col) covered.add(cellKey(r, c));
      }
    }
  }

  return (
    <div className="overflow-auto rounded border border-neutral-800">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-neutral-900 p-1" />
            {Array.from({ length: sheet.n_cols }, (_, col) => (
              <th
                key={col}
                className="bg-neutral-900 px-2 py-1 font-mono font-normal text-neutral-500"
              >
                {columnLabel(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: sheet.n_rows }, (_, row) => (
            <tr key={row}>
              <th className="sticky left-0 z-10 bg-neutral-900 px-2 py-1 font-mono font-normal text-neutral-500">
                {row + 1}
              </th>
              {Array.from({ length: sheet.n_cols }, (_, col) => {
                const key = cellKey(row, col);
                if (covered.has(key)) return null;

                const cell = byPosition.get(key);
                const value = edits[key] ?? cell?.text ?? "";
                const isDisputed = disputed.has(key);
                const isLowConfidence =
                  cell !== undefined && cell.confidence < CONFIDENCE_WARN;
                const isEdited = key in edits;

                return (
                  <td
                    key={col}
                    colSpan={cell?.col_span ?? 1}
                    rowSpan={cell?.row_span ?? 1}
                    onClick={() => cell && setEditing(key)}
                    className={[
                      "cursor-text border border-neutral-800 px-2 py-1 align-middle",
                      isDisputed ? "bg-amber-950/60 ring-1 ring-amber-600" : "",
                      !isDisputed && isLowConfidence ? "bg-sky-950/40" : "",
                      isEdited ? "bg-emerald-950/60 ring-1 ring-emerald-600" : "",
                    ].join(" ")}
                    title={
                      cell
                        ? `${cell.source} · confidence ${(cell.confidence * 100).toFixed(0)}%`
                        : undefined
                    }
                  >
                    {editing === key && cell ? (
                      <input
                        autoFocus
                        defaultValue={value}
                        onBlur={(event) => {
                          onEdit(cell, event.target.value);
                          setEditing(null);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                          if (event.key === "Escape") setEditing(null);
                        }}
                        className="w-full bg-neutral-800 px-1 text-neutral-100 outline-none"
                      />
                    ) : (
                      <span className="whitespace-nowrap">{value}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
