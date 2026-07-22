"use client";

import { useState } from "react";

import type { CitationResponse } from "@/types/api-schemas";

/** Renders only the learner-safe citation fields the backend provides
 * - never a chunk id, embedding vector, or raw prompt text (those
 * never appear in `CitationResponse` to begin with). */
export function CitationList({ citations }: { citations: CitationResponse[] }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  if (citations.length === 0) return null;

  const toggle = (citationNumber: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(citationNumber)) {
        next.delete(citationNumber);
      } else {
        next.add(citationNumber);
      }
      return next;
    });
  };

  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="text-xs font-medium text-muted">Sources</p>
      <ul className="flex flex-col gap-1.5">
        {citations.map((citation) => {
          const isExpanded = expanded.has(citation.citation_number);
          return (
            <li key={citation.citation_number} className="rounded-lg border border-border bg-slate-50 text-xs">
              <button
                type="button"
                onClick={() => toggle(citation.citation_number)}
                aria-expanded={isExpanded}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-medium text-slate-800"
              >
                <span>
                  [{citation.citation_number}] {citation.document_title}
                  {citation.heading_path.length > 0 ? ` — ${citation.heading_path.join(" > ")}` : ""}
                </span>
                <span aria-hidden="true">{isExpanded ? "−" : "+"}</span>
              </button>
              {isExpanded ? (
                <div className="border-t border-border px-3 py-2 text-slate-600">
                  <p className="italic">&ldquo;{citation.excerpt}&rdquo;</p>
                  <p className="mt-1 text-slate-500">Source: {citation.source_title}</p>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
