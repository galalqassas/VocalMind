import { useState, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router";
import { parse, isValid } from "date-fns";
import {
  Search, ArrowDown, ArrowUp, Loader2, AlertTriangle,
  RefreshCw, Upload, MoreHorizontal, Eye, RotateCcw,
} from "lucide-react";
import {
  getInteractionDetail,
  getInteractions,
  getAgents,
  createInteraction,
  reprocessInteraction,
  type InteractionSummary,
  type AgentSummary,
} from "../../services/api";

function getFailurePreview(row: InteractionSummary): string {
  const failures = row.processingFailures || [];
  if (!failures.length) {
    return String(row.status).toLowerCase() === "failed"
      ? "Processing failed (no error text stored)."
      : "";
  }

  const grouped = new Map<string, { message: string; stages: string[] }>();
  for (const failure of failures) {
    const stage = (failure.stage || "unknown").trim() || "unknown";
    const message = (failure.errorMessage || "Unknown error").trim() || "Unknown error";
    const key = message.toLowerCase();
    const current = grouped.get(key);
    if (current) {
      current.stages.push(stage);
      continue;
    }
    grouped.set(key, { message, stages: [stage] });
  }

  return Array.from(grouped.values())
    .map((group) =>
      group.stages.length > 1
        ? `${group.stages.join(", ")}: ${group.message}`
        : `${group.stages[0]}: ${group.message}`,
    )
    .join(" | ");
}

function isFailedStatus(row: InteractionSummary): boolean {
  return String(row.status || "").toLowerCase() === "failed";
}

function isProcessingStatus(row: InteractionSummary): boolean {
  const s = String(row.status || "").toLowerCase();
  return s === "processing" || s === "pending";
}

function interactionDateMs(row: InteractionSummary): number {
  const datePart = (row.date || "").trim();
  const timePart = (row.time || "").trim();
  if (!datePart) return 0;

  if (timePart) {
    const combined = `${datePart} ${timePart}`;
    const withPaddedHour = parse(combined, "yyyy-MM-dd hh:mm a", new Date());
    if (isValid(withPaddedHour)) return withPaddedHour.getTime();
    const withHour = parse(combined, "yyyy-MM-dd h:mm a", new Date());
    if (isValid(withHour)) return withHour.getTime();
  }

  const dateOnly = parse(datePart, "yyyy-MM-dd", new Date());
  return isValid(dateOnly) ? dateOnly.getTime() : 0;
}

const POLL_INTERVAL = 8000;

export function SessionInspector() {
  const [interactions, setInteractions] = useState<InteractionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reprocessingIds, setReprocessingIds] = useState<Set<string>>(new Set());

  const [searchQuery, setSearchQuery] = useState("");
  const [sortField, setSortField] = useState<"score" | "date" | "duration">("score");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  // Upload state
  const [showUpload, setShowUpload] = useState(false);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Action menu
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!openMenuId) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openMenuId]);

  // Initial fetch
  useEffect(() => {
    getInteractions()
      .then(setInteractions)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  // Poll for processing rows
  const hasProcessing = interactions.some(isProcessingStatus);
  useEffect(() => {
    if (!hasProcessing) return;
    const timer = setInterval(() => {
      getInteractions()
        .then(setInteractions)
        .catch(() => {});
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [hasProcessing]);

  // Fetch agents when upload dialog opens
  useEffect(() => {
    if (!showUpload) return;
    getAgents().then(setAgents).catch(() => {});
  }, [showUpload]);

  const handleSort = (field: "score" | "date" | "duration") => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortOrder("asc");
    }
    setCurrentPage(1);
  };

  const handleReprocess = async (interactionId: string) => {
    setActionError(null);
    setOpenMenuId(null);
    setReprocessingIds((prev) => new Set(prev).add(interactionId));
    try {
      await reprocessInteraction(interactionId);
      const refreshed = await getInteractions();
      setInteractions(refreshed);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reprocess interaction";
      if (message.includes("409")) {
        try {
          await reprocessInteraction(interactionId, { force: true });
          const refreshed = await getInteractions();
          setInteractions(refreshed);
          return;
        } catch {
          setActionError("This interaction is already processing. Please wait and try again.");
        }
      } else {
        setActionError(message);
      }
    } finally {
      setReprocessingIds((prev) => {
        const next = new Set(prev);
        next.delete(interactionId);
        return next;
      });
    }
  };

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    setActionError(null);
    try {
      await createInteraction(file, selectedAgent || undefined);
      setShowUpload(false);
      setSelectedAgent("");
      const refreshed = await getInteractions();
      setInteractions(refreshed);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [selectedAgent]);

  const filteredInteractions = interactions.filter((interaction) => {
    const searchLower = searchQuery.toLowerCase();
    return (
      interaction.agentName.toLowerCase().includes(searchLower) ||
      interaction.id.toLowerCase().includes(searchLower) ||
      interaction.date.toLowerCase().includes(searchLower)
    );
  });

  const sortedInteractions = [...filteredInteractions].sort((a, b) => {
    let comparison = 0;
    if (sortField === "score") {
      comparison = a.overallScore - b.overallScore;
    } else if (sortField === "date") {
      const dateA = interactionDateMs(a);
      const dateB = interactionDateMs(b);
      comparison = dateA - dateB;
      if (comparison === 0) comparison = a.id.localeCompare(b.id);
    } else if (sortField === "duration") {
      const [mA, sA] = a.duration.split(":").map(Number);
      const [mB, sB] = b.duration.split(":").map(Number);
      comparison = ((mA || 0) * 60 + (sA || 0)) - ((mB || 0) * 60 + (sB || 0));
    }
    return sortOrder === "asc" ? -comparison : comparison;
  });

  const totalItems = sortedInteractions.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
  const startIndex = (currentPage - 1) * itemsPerPage;
  const paginatedInteractions = sortedInteractions.slice(startIndex, startIndex + itemsPerPage);

  const sortIndicator = (field: "score" | "date" | "duration") => {
    if (sortField !== field) return null;
    return sortOrder === "asc" ? (
      <ArrowUp className="ml-1 h-3.5 w-3.5" />
    ) : (
      <ArrowDown className="ml-1 h-3.5 w-3.5" />
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <span className="ml-3 text-muted-foreground text-sm">Loading interactions...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <AlertTriangle className="w-10 h-10 text-destructive mx-auto mb-3" />
          <p className="text-foreground text-sm">Failed to load interactions</p>
          <p className="text-muted-foreground/80 text-xs mt-1">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 min-w-0 max-w-full">
      {actionError && (
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-[12px] font-medium text-destructive">
          {actionError}
        </div>
      )}

      {/* Controls row — no duplicate heading */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          {totalItems} interaction{totalItems !== 1 ? "s" : ""} · sorted by {sortField} (
          {sortOrder === "asc" ? "descending" : "ascending"})
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search agent, date, ID…"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              className="w-[200px] h-10 pl-9 pr-3 bg-muted/20 border border-border rounded-[10px] text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
            />
          </div>

          <div className="flex items-center border border-border rounded-[10px] overflow-hidden bg-card">
            {(["score", "date", "duration"] as const).map((field) => (
              <button
                key={field}
                type="button"
                onClick={() => handleSort(field)}
                className={`flex items-center px-3 h-10 text-[11px] font-semibold transition-colors capitalize ${
                  sortField === field
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {field}
                {sortIndicator(field)}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => setShowUpload(true)}
            className="inline-flex h-10 items-center gap-2 rounded-[10px] bg-primary px-4 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Upload className="w-4 h-4" />
            Upload call
          </button>
        </div>
      </div>

      {/* Upload Dialog */}
      {showUpload && (
        <div className="mb-5 bg-card rounded-xl border border-border p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-bold text-foreground">Upload Call Recording</h3>
            <button type="button" onClick={() => setShowUpload(false)}
              className="text-muted-foreground hover:text-foreground text-[18px] leading-none">&times;</button>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Agent (optional)</label>
              <select
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                className="w-full h-10 rounded-lg border border-border bg-background px-3 text-[13px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              >
                <option value="">Auto-detect</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
            <div>
              <input ref={fileInputRef} type="file" accept="audio/*" className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleUpload(file);
                }} />
              <button type="button" disabled={uploading}
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                {uploading ? "Uploading..." : "Choose file"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="bg-card rounded-[14px] border border-border">
        <div className="overflow-x-auto rounded-t-[14px]">
          <table className="w-full min-w-[56rem] border-collapse">
            <thead>
              <tr className="bg-muted/10 border-b border-border">
                <th className="px-4 py-4 text-left text-label">Agent</th>
                <th className="px-4 py-4 text-left text-label">Date & Time</th>
                <th className="px-4 py-4 text-left text-label">Duration</th>
                <th className="px-4 py-4 text-left text-label">Score</th>
                <th className="px-4 py-4 text-left text-label">Empathy</th>
                <th className="px-4 py-4 text-left text-label">Policy</th>
                <th className="px-4 py-4 text-left text-label">Resolution</th>
                <th className="px-4 py-4 text-center text-label">Status</th>
                <th className="px-3 py-4 text-center text-label sticky right-0 z-30 w-32 min-w-[8rem] border-l border-border bg-muted/10 shadow-[-6px_0_10px_-6px_rgba(0,0,0,0.12)]">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {paginatedInteractions.map((row) => {
                const failed = isFailedStatus(row);
                const processing = isProcessingStatus(row);
                const isReprocessing = reprocessingIds.has(row.id);

                return (
                  <tr
                    key={row.id}
                    className={`group hover:bg-muted/5 transition-colors ${failed ? "bg-destructive/[0.04]" : ""}`}
                  >
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-[14px] font-semibold text-foreground">{row.agentName}</span>
                          {row.hasViolation && (
                            <span className="px-2 py-0.5 bg-destructive/10 text-destructive rounded-full text-[10px] font-medium">
                              Violation
                            </span>
                          )}
                        </div>
                        {failed && row.processingFailures && row.processingFailures.length > 0 && (
                          <span className="text-[11px] text-destructive/70 line-clamp-1" title={getFailurePreview(row)}>
                            {getFailurePreview(row)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="text-[13px] font-medium text-foreground">{row.date}</div>
                      <div className="text-[11px] text-muted-foreground">{row.time}</div>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-[13px] text-muted-foreground">
                      {row.duration}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span
                        className="text-[18px] font-bold"
                        style={{
                          color: row.overallScore >= 85 ? "var(--success)" : row.overallScore >= 75 ? "var(--primary)" : "var(--destructive)",
                        }}
                      >
                        {row.overallScore}<span className="text-[12px] font-semibold text-muted-foreground">%</span>
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-[13px] text-foreground">{row.empathyScore}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-[13px] text-foreground">{row.policyScore}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-[13px] text-foreground">{row.resolutionScore}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-center align-middle">
                      <div className="flex justify-center">
                        {processing || isReprocessing ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border bg-primary/5 text-primary border-primary/20">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            Processing
                          </span>
                        ) : failed ? (
                          <span className="px-2.5 py-1 rounded-full text-[11px] font-bold border bg-destructive/5 text-destructive border-destructive/20">
                            Failed
                          </span>
                        ) : row.resolved ? (
                          <span className="px-2.5 py-1 rounded-full text-[11px] font-bold border bg-success/5 text-success border-success/20">
                            Resolved
                          </span>
                        ) : (
                          <span className="px-2.5 py-1 rounded-full text-[11px] font-bold border bg-muted text-muted-foreground border-border">
                            Unresolved
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Actions — sticky */}
                    <td
                      className={`sticky right-0 z-20 whitespace-nowrap border-l border-border/80 px-3 py-4 text-center align-middle shadow-[-6px_0_10px_-6px_rgba(0,0,0,0.1)] ${
                        failed ? "bg-destructive/[0.04] group-hover:bg-muted/5" : "bg-card group-hover:bg-muted/5"
                      }`}
                    >
                      <div className="flex items-center justify-center gap-1.5">
                        <Link
                          to={`/manager/inspector/${row.id}`}
                          onMouseEnter={() => {
                            void getInteractionDetail(row.id).catch(() => undefined);
                          }}
                          className="inline-flex h-8 items-center gap-1 rounded-lg bg-primary/10 px-3 text-[12px] font-semibold text-primary hover:bg-primary/20 transition-colors"
                        >
                          Inspect
                          <ArrowDown className="w-3 h-3 -rotate-90" />
                        </Link>

                        {/* More menu */}
                        <div className="relative" ref={openMenuId === row.id ? menuRef : undefined}>
                          <button
                            type="button"
                            onClick={() => setOpenMenuId(openMenuId === row.id ? null : row.id)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                          >
                            <MoreHorizontal className="w-4 h-4" />
                          </button>
                          {openMenuId === row.id && (
                            <div className="absolute right-0 top-full mt-1 w-44 rounded-lg border border-border bg-card shadow-lg z-50 py-1">
                              <Link
                                to={`/manager/inspector/${row.id}`}
                                className="flex items-center gap-2 px-3 py-2 text-[12px] text-foreground hover:bg-muted transition-colors"
                                onClick={() => setOpenMenuId(null)}
                              >
                                <Eye className="w-3.5 h-3.5" />
                                View details
                              </Link>
                              <button
                                type="button"
                                onClick={() => void handleReprocess(row.id)}
                                disabled={isReprocessing || processing}
                                className="flex items-center gap-2 w-full px-3 py-2 text-[12px] text-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <RotateCcw className={`w-3.5 h-3.5 ${isReprocessing ? "animate-spin" : ""}`} />
                                {isReprocessing ? "Reprocessing..." : "Reprocess"}
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="px-6 py-4 bg-muted/5 border-t border-border flex items-center justify-between rounded-b-[14px]">
          <div className="text-[13px] text-muted-foreground font-medium">
            Showing {totalItems > 0 ? startIndex + 1 : 0}–{Math.min(startIndex + itemsPerPage, totalItems)} of {totalItems}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="h-9 px-4 rounded-xl border border-border bg-background text-[13px] font-semibold text-foreground hover:bg-muted disabled:opacity-40 transition-all"
            >
              Previous
            </button>
            <span className="px-3 text-[12px] text-muted-foreground tabular-nums">{currentPage} / {totalPages}</span>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages || totalItems === 0}
              className="h-9 px-4 rounded-xl border border-border bg-background text-[13px] font-semibold text-foreground hover:bg-muted disabled:opacity-40 transition-all"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
