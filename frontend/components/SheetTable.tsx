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
    <div className="panel max-h-[70vh] overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 z-20">
          <tr>
            <th className="sticky left-0 z-30 bg-[--canvas] p-1" />
            {Array.from({ length: sheet.n_cols }, (_, col) => (
              <th
                key={col}
                className="border-b border-light-grey bg-[--canvas] px-2 py-1.5 font-mono text-[11px] font-normal text-telecom/45"
              >
                {columnLabel(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: sheet.n_rows }, (_, row) => (
            <tr key={row}>
              <th className="sticky left-0 z-10 border-r border-light-grey bg-[--canvas] px-2 py-1 font-mono text-[11px] font-normal text-telecom/45">
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
                      "max-w-[22rem] cursor-text truncate border border-light-grey/70 px-2 py-1 align-middle text-telecom",
                      isDisputed ? "bg-care/10 ring-1 ring-inset ring-care/50" : "",
                      !isDisputed && isLowConfidence ? "bg-aqua/10" : "",
                      isEdited ? "bg-money/15 ring-1 ring-inset ring-money/60" : "",
                    ].join(" ")}
                    title={
                      cell
                        ? `${cell.source} · ${(cell.confidence * 100).toFixed(0)}% confidence`
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
                        className="w-full rounded bg-white px-1 text-telecom outline-none ring-2 ring-digital"
                      />
                    ) : (
                      value
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
