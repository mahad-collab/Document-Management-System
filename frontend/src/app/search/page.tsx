"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import { Card, ErrorBanner, EmptyState, PrimaryButton, TextInput, Label, Badge, formatBytes, formatDate } from "@/components/ui";
import type { DocumentItem } from "@/lib/types";

const OCR_BADGE: Record<string, "slate" | "green" | "red" | "amber" | "blue"> = {
  pending: "slate",
  processing: "blue",
  completed: "green",
  failed: "red",
  skipped: "slate",
};

function SearchBody() {
  const { selectedDepartmentId, selectedDepartment } = useApp();
  const [q, setQ] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [tags, setTags] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [results, setResults] = useState<DocumentItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedDepartmentId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.search({
        department_id: selectedDepartmentId,
        q: q || undefined,
        document_type: documentType || undefined,
        tags: tags || undefined,
        document_date_from: dateFrom || undefined,
        document_date_to: dateTo || undefined,
      });
      setResults(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  if (!selectedDepartmentId) {
    return <EmptyState message="No department selected — pick one from the top bar." />;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">
        Search {selectedDepartment && <span className="text-slate-400">— {selectedDepartment.name}</span>}
      </h1>

      <Card>
        <form onSubmit={handleSearch} className="space-y-4">
          <div>
            <Label>Full-text query</Label>
            <TextInput
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search filename, metadata, and OCR-extracted text…"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <div>
              <Label>Document type</Label>
              <TextInput value={documentType} onChange={(e) => setDocumentType(e.target.value)} />
            </div>
            <div>
              <Label>Tags (comma-separated)</Label>
              <TextInput value={tags} onChange={(e) => setTags(e.target.value)} />
            </div>
            <div>
              <Label>From date</Label>
              <TextInput type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </div>
            <div>
              <Label>To date</Label>
              <TextInput type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </div>
          </div>
          <PrimaryButton type="submit" disabled={loading}>
            {loading ? "Searching…" : "Search"}
          </PrimaryButton>
        </form>
      </Card>

      {error && <ErrorBanner message={error} />}

      {results !== null && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-slate-900">{results.length} result{results.length === 1 ? "" : "s"}</h2>
          {results.length === 0 ? (
            <EmptyState message="No matching documents." />
          ) : (
            <div className="space-y-2">
              {results.map((doc) => (
                <div key={doc.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 px-4 py-3 text-sm">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-slate-900">{doc.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <span>{formatBytes(doc.file_size)}</span>
                      <span>{formatDate(doc.created_at)}</span>
                      {doc.document_type && <Badge>{doc.document_type}</Badge>}
                      <Badge color={OCR_BADGE[doc.ocr_status] ?? "slate"}>OCR: {doc.ocr_status}</Badge>
                    </div>
                  </div>
                  <a
                    href={api.downloadUrl(doc.id)}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Download
                  </a>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <RequireAuth>
      <SearchBody />
    </RequireAuth>
  );
}
