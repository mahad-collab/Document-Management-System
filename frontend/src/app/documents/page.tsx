"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import RequireAuth from "@/components/RequireAuth";
import {
  Card,
  ErrorBanner,
  EmptyState,
  PrimaryButton,
  SecondaryButton,
  TextInput,
  Label,
  Badge,
  formatBytes,
  formatDate,
} from "@/components/ui";
import type { DocumentItem, DocumentVersion, Folder, UUID } from "@/lib/types";

const OCR_BADGE: Record<string, "slate" | "green" | "red" | "amber" | "blue"> = {
  pending: "slate",
  processing: "blue",
  completed: "green",
  failed: "red",
  skipped: "slate",
};

function FolderBrowserBody() {
  const { selectedDepartmentId, selectedDepartment } = useApp();
  const [stack, setStack] = useState<Folder[]>([]); // breadcrumb trail; [] = department root
  const [folders, setFolders] = useState<Folder[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState<UUID | null>(null);

  const currentFolder = stack[stack.length - 1] ?? null;

  const load = useCallback(async () => {
    if (!selectedDepartmentId) return;
    setLoading(true);
    setError(null);
    try {
      const folderList = await api.listFolders(selectedDepartmentId, currentFolder?.id ?? null);
      setFolders(folderList);

      if (currentFolder) {
        if (showRecycleBin) {
          const results = await api.search({
            department_id: selectedDepartmentId,
            folder_id: currentFolder.id,
            include_deleted: true,
          });
          setDocuments(results.filter((d) => d.is_deleted));
        } else {
          const docs = await api.listDocuments({ department_id: selectedDepartmentId, folder_id: currentFolder.id });
          setDocuments(docs);
        }
      } else {
        setDocuments([]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [selectedDepartmentId, currentFolder, showRecycleBin]);

  useEffect(() => {
    load();
  }, [load]);

  // Reset navigation whenever the active department changes.
  useEffect(() => {
    setStack([]);
    setShowRecycleBin(false);
  }, [selectedDepartmentId]);

  async function handleCreateFolder(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedDepartmentId) return;
    setCreatingFolder(true);
    setError(null);
    try {
      await api.createFolder({
        name: newFolderName,
        department_id: selectedDepartmentId,
        parent_id: currentFolder?.id ?? null,
      });
      setNewFolderName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create folder");
    } finally {
      setCreatingFolder(false);
    }
  }

  async function handleArchiveFolder(id: UUID) {
    setError(null);
    try {
      await api.archiveFolder(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to archive folder");
    }
  }

  async function handleDeleteDoc(id: UUID) {
    setError(null);
    try {
      await api.deleteDocument(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete document");
    }
  }

  async function handleRestoreDoc(id: UUID) {
    setError(null);
    try {
      await api.restoreDocument(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to restore document");
    }
  }

  async function handlePermanentDelete(id: UUID) {
    if (!confirm("Permanently delete this document? This cannot be undone.")) return;
    setError(null);
    try {
      await api.permanentDeleteDocument(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to permanently delete");
    }
  }

  async function handleRetryOcr(id: UUID) {
    setError(null);
    try {
      await api.retryOcr(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to retry OCR");
    }
  }

  if (!selectedDepartmentId) {
    return <EmptyState message="No department selected — pick one from the top bar." />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Documents</h1>
          <Breadcrumb
            departmentName={selectedDepartment?.name ?? ""}
            stack={stack}
            onNavigate={(index) => setStack(index < 0 ? [] : stack.slice(0, index + 1))}
          />
        </div>
        {currentFolder && (
          <SecondaryButton onClick={() => setShowRecycleBin((v) => !v)}>
            {showRecycleBin ? "Back to documents" : "Recycle bin"}
          </SecondaryButton>
        )}
      </div>

      {error && <ErrorBanner message={error} />}

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-slate-900">Create {currentFolder ? "subfolder" : "folder"}</h2>
        <form onSubmit={handleCreateFolder} className="flex gap-2">
          <TextInput
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            placeholder="Folder name"
            required
            className="max-w-xs"
          />
          <PrimaryButton type="submit" disabled={creatingFolder}>
            {creatingFolder ? "Creating…" : "Create"}
          </PrimaryButton>
        </form>
      </Card>

      {loading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : (
        <>
          {folders.length > 0 && (
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-slate-900">Folders</h2>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                {folders.map((f) => (
                  <div key={f.id} className="group flex items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm">
                    <button onClick={() => setStack([...stack, f])} className="truncate text-left text-slate-700 hover:underline">
                      📁 {f.name}
                    </button>
                    <button
                      onClick={() => handleArchiveFolder(f.id)}
                      title="Archive folder"
                      className="ml-2 hidden text-xs text-slate-400 hover:text-red-600 group-hover:inline"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {currentFolder ? (
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-900">
                  {showRecycleBin ? "Deleted documents" : "Documents"}
                </h2>
              </div>

              {!showRecycleBin && <UploadForm folderId={currentFolder.id} onUploaded={load} />}

              {documents.length === 0 ? (
                <EmptyState message={showRecycleBin ? "Recycle bin is empty." : "No documents in this folder yet."} />
              ) : (
                <div className="mt-4 space-y-2">
                  {documents.map((doc) => (
                    <DocumentRow
                      key={doc.id}
                      doc={doc}
                      expanded={expandedDoc === doc.id}
                      onToggleExpand={() => setExpandedDoc(expandedDoc === doc.id ? null : doc.id)}
                      onDelete={() => handleDeleteDoc(doc.id)}
                      onRestore={() => handleRestoreDoc(doc.id)}
                      onPermanentDelete={() => handlePermanentDelete(doc.id)}
                      onVersionUploaded={load}
                      onRetryOcr={() => handleRetryOcr(doc.id)}
                      inRecycleBin={showRecycleBin}
                    />
                  ))}
                </div>
              )}
            </Card>
          ) : (
            folders.length === 0 && <EmptyState message="No folders yet — create one above to start uploading documents." />
          )}
        </>
      )}
    </div>
  );
}

function Breadcrumb({
  departmentName,
  stack,
  onNavigate,
}: {
  departmentName: string;
  stack: Folder[];
  onNavigate: (index: number) => void;
}) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-sm text-slate-500">
      <button onClick={() => onNavigate(-1)} className="hover:underline">
        {departmentName}
      </button>
      {stack.map((f, i) => (
        <span key={f.id} className="flex items-center gap-1">
          <span>/</span>
          <button onClick={() => onNavigate(i)} className="hover:underline">
            {f.name}
          </button>
        </span>
      ))}
    </div>
  );
}

function UploadForm({ folderId, onUploaded }: { folderId: UUID; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState("");
  const [documentNumber, setDocumentNumber] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("folder_id", folderId);
      if (documentType) form.set("document_type", documentType);
      if (documentNumber) form.set("document_number", documentNumber);
      if (description) form.set("description", description);
      form.set("tags", tags);
      form.set("file", file);
      await api.uploadDocument(form);
      setFile(null);
      setDocumentType("");
      setDocumentNumber("");
      setDescription("");
      setTags("");
      (document.getElementById("upload-file-input") as HTMLInputElement | null)?.value &&
        ((document.getElementById("upload-file-input") as HTMLInputElement).value = "");
      onUploaded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mb-4 rounded-md border border-dashed border-slate-300 p-4">
      {error && <div className="mb-3"><ErrorBanner message={error} /></div>}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label>File (PDF, JPG, PNG, TIFF — under 4MB)</Label>
          <input
            id="upload-file-input"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.tiff"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
            className="block w-full text-sm"
          />
        </div>
        <div>
          <Label>Document type (optional)</Label>
          <TextInput value={documentType} onChange={(e) => setDocumentType(e.target.value)} />
        </div>
        <div>
          <Label>Document number (optional)</Label>
          <TextInput value={documentNumber} onChange={(e) => setDocumentNumber(e.target.value)} />
        </div>
        <div>
          <Label>Tags (comma-separated, optional)</Label>
          <TextInput value={tags} onChange={(e) => setTags(e.target.value)} placeholder="invoice, q3" />
        </div>
        <div className="sm:col-span-2">
          <Label>Description (optional)</Label>
          <TextInput value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </div>
      <PrimaryButton type="submit" disabled={uploading || !file} className="mt-3">
        {uploading ? "Uploading…" : "Upload"}
      </PrimaryButton>
    </form>
  );
}

function DocumentRow({
  doc,
  expanded,
  onToggleExpand,
  onDelete,
  onRestore,
  onPermanentDelete,
  onVersionUploaded,
  onRetryOcr,
  inRecycleBin,
}: {
  doc: DocumentItem;
  expanded: boolean;
  onToggleExpand: () => void;
  onDelete: () => void;
  onRestore: () => void;
  onPermanentDelete: () => void;
  onVersionUploaded: () => void;
  onRetryOcr: () => void;
  inRecycleBin: boolean;
}) {
  return (
    <div className="rounded-md border border-slate-200">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <button onClick={onToggleExpand} className="truncate text-left text-sm font-medium text-slate-900 hover:underline">
            {doc.name}
          </button>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>{formatBytes(doc.file_size)}</span>
            <span>v{doc.current_version_number}</span>
            <span>{formatDate(doc.created_at)}</span>
            {doc.document_type && <Badge>{doc.document_type}</Badge>}
            <Badge color={OCR_BADGE[doc.ocr_status] ?? "slate"}>OCR: {doc.ocr_status}</Badge>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!inRecycleBin ? (
            <>
              <a
                href={api.downloadUrl(doc.id)}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                Download
              </a>
              <SecondaryButton onClick={onToggleExpand} className="px-3 py-1.5 text-xs">
                Versions
              </SecondaryButton>
              {doc.ocr_status === "failed" && (
                <SecondaryButton onClick={onRetryOcr} className="px-3 py-1.5 text-xs">
                  Retry OCR
                </SecondaryButton>
              )}
              <SecondaryButton onClick={onDelete} className="px-3 py-1.5 text-xs text-red-600">
                Delete
              </SecondaryButton>
            </>
          ) : (
            <>
              <SecondaryButton onClick={onRestore} className="px-3 py-1.5 text-xs">
                Restore
              </SecondaryButton>
              <SecondaryButton onClick={onPermanentDelete} className="px-3 py-1.5 text-xs text-red-600">
                Delete permanently
              </SecondaryButton>
            </>
          )}
        </div>
      </div>
      {expanded && !inRecycleBin && <VersionHistory documentId={doc.id} onVersionUploaded={onVersionUploaded} />}
    </div>
  );
}

function VersionHistory({ documentId, onVersionUploaded }: { documentId: UUID; onVersionUploaded: () => void }) {
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [changeDescription, setChangeDescription] = useState("");
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    api
      .listVersions(documentId)
      .then(setVersions)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load versions"))
      .finally(() => setLoading(false));
  }, [documentId]);

  async function handleUploadVersion(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      if (changeDescription) form.set("change_description", changeDescription);
      form.set("file", file);
      await api.uploadNewVersion(documentId, form);
      setFile(null);
      setChangeDescription("");
      const fresh = await api.listVersions(documentId);
      setVersions(fresh);
      onVersionUploaded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to upload new version");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="border-t border-slate-100 bg-slate-50 px-4 py-3">
      {error && <div className="mb-2"><ErrorBanner message={error} /></div>}
      {loading ? (
        <p className="text-xs text-slate-400">Loading versions…</p>
      ) : (
        <ul className="space-y-1 text-xs text-slate-600">
          {versions.map((v) => (
            <li key={v.id} className="flex items-center justify-between">
              <span>
                v{v.version_number} — {v.change_description || "no description"} ({formatBytes(v.file_size)})
              </span>
              <span className="text-slate-400">{formatDate(v.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={handleUploadVersion} className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.tiff"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-xs"
        />
        <TextInput
          value={changeDescription}
          onChange={(e) => setChangeDescription(e.target.value)}
          placeholder="What changed?"
          className="max-w-[200px] py-1 text-xs"
        />
        <PrimaryButton type="submit" disabled={uploading || !file} className="px-3 py-1.5 text-xs">
          {uploading ? "Uploading…" : "Upload new version"}
        </PrimaryButton>
      </form>
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <RequireAuth>
      <FolderBrowserBody />
    </RequireAuth>
  );
}
