"use client";

import { useState } from "react";
import { format, subDays } from "date-fns";
import { Download, FileJson, FileSpreadsheet, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { cn } from "@/lib/utils";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, EXPORT_ENDPOINTS } from "@/utils/api-endpoints";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, MemoryExport } from "@/types/api";

const ALL_VALUES = "__all__";

const DATE_RANGES = {
  all: { label: "All time", days: null },
  "1": { label: "Last 24 hours", days: 1 },
  "7": { label: "Last 7 days", days: 7 },
  "30": { label: "Last 30 days", days: 30 },
} as const;
type DateRangeKey = keyof typeof DATE_RANGES;

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  failed: "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  pending: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

export default function ExportPage() {
  const [format_, setFormat] = useState<"json" | "csv">("json");
  const [userId, setUserId] = useState(ALL_VALUES);
  const [agentId, setAgentId] = useState(ALL_VALUES);
  const [runId, setRunId] = useState(ALL_VALUES);
  const [project, setProject] = useState(ALL_VALUES);
  const [dateRange, setDateRange] = useState<DateRangeKey>("all");
  const [isCreating, setIsCreating] = useState(false);
  const [exportToDelete, setExportToDelete] = useState<MemoryExport | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const { data: entities = [] } = useApiQuery<Entity[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load entities", initialData: [] },
  );

  const byType = (type: Entity["type"]) =>
    entities.filter((e) => e.type === type).map((e) => e.id).sort();

  const {
    data: exports = [],
    isLoading,
    refetch,
  } = useApiQuery<MemoryExport[]>(
    async () => {
      const res = await api.get<MemoryExport[]>(EXPORT_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load export history", initialData: [] },
  );

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      const range = DATE_RANGES[dateRange];
      await api.post(EXPORT_ENDPOINTS.CREATE, {
        format: format_,
        user_id: userId === ALL_VALUES ? undefined : userId,
        agent_id: agentId === ALL_VALUES ? undefined : agentId,
        run_id: runId === ALL_VALUES ? undefined : runId,
        project: project === ALL_VALUES ? undefined : project,
        date_from: range.days ? subDays(new Date(), range.days).toISOString() : undefined,
      });
      toast({ title: "Export created", variant: "success" });
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to create export",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setIsCreating(false);
    }
  };

  const handleDownload = async (row: MemoryExport) => {
    setDownloadingId(row.id);
    try {
      const res = await api.get(EXPORT_ENDPOINTS.DOWNLOAD(row.id), {
        responseType: "blob",
      });
      const blob = new Blob([res.data], {
        type: row.format === "csv" ? "text/csv" : "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `memories-${row.id}.${row.format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast({
        title: "Failed to download export",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    } finally {
      setDownloadingId(null);
    }
  };

  const handleDelete = async () => {
    if (!exportToDelete) return;
    try {
      await api.delete(EXPORT_ENDPOINTS.BY_ID(exportToDelete.id));
      toast({ title: "Export deleted", variant: "success" });
      setExportToDelete(null);
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to delete export",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    }
  };

  const columns = [
    {
      key: "format" as keyof MemoryExport,
      label: "Format",
      width: 90,
      render: (value: string) => <span className="uppercase text-xs font-medium">{value}</span>,
    },
    {
      key: "status" as keyof MemoryExport,
      label: "Status",
      width: 110,
      render: (value: string) => (
        <Badge
          variant="outline"
          className={cn("px-1.5 py-0 text-[10px] capitalize border-0", STATUS_BADGE[value])}
        >
          {value}
        </Badge>
      ),
    },
    {
      key: "filters" as keyof MemoryExport,
      label: "Filters",
      width: 220,
      render: (value: Record<string, string>) => {
        const entries = Object.entries(value ?? {});
        if (entries.length === 0) return <span className="text-onSurface-default-tertiary">All memories</span>;
        return (
          <span className="text-xs font-mono truncate">
            {entries.map(([k, v]) => `${k}=${v}`).join(" ")}
          </span>
        );
      },
    },
    {
      key: "record_count" as keyof MemoryExport,
      label: "Records",
      width: 90,
    },
    {
      key: "created_at" as keyof MemoryExport,
      label: "Created",
      width: 140,
      render: (value: string) => format(new Date(value), "MMM d, yyyy HH:mm"),
    },
    {
      key: "id" as keyof MemoryExport,
      label: "",
      width: 90,
      render: (_: string, row: MemoryExport) => (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            disabled={downloadingId === row.id}
            onClick={() => void handleDownload(row)}
          >
            <Download className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => setExportToDelete(row)}
          >
            <Trash2 className="size-3.5 text-onSurface-danger-primary" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold font-fustat">Export</h1>
        <p className="text-sm text-onSurface-default-secondary">
          Export your memories in JSON or CSV format.
        </p>
      </div>

      <Card className="border-memBorder-primary">
        <CardContent className="p-6 space-y-4">
          <div className="space-y-2">
            <span className="text-sm font-medium">Format</span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFormat("json")}
                className={format_ === "json" ? "border-memPurple-300" : ""}
              >
                <FileJson className="size-3.5 mr-1.5" /> JSON
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFormat("csv")}
                className={format_ === "csv" ? "border-memPurple-300" : ""}
              >
                <FileSpreadsheet className="size-3.5 mr-1.5" /> CSV
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <span className="text-sm font-medium">Entity filters</span>
            <div className="flex flex-wrap gap-2">
              <Select value={project} onValueChange={setProject}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="All projects" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUES}>All projects</SelectItem>
                  {byType("project").map((id) => (
                    <SelectItem key={id} value={id}>
                      {id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={userId} onValueChange={setUserId}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="All users" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUES}>All users</SelectItem>
                  {byType("user").map((id) => (
                    <SelectItem key={id} value={id}>
                      {id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={agentId} onValueChange={setAgentId}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="All agents" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUES}>All agents</SelectItem>
                  {byType("agent").map((id) => (
                    <SelectItem key={id} value={id}>
                      {id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={runId} onValueChange={setRunId}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="All runs" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUES}>All runs</SelectItem>
                  {byType("run").map((id) => (
                    <SelectItem key={id} value={id}>
                      {id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <span className="text-sm font-medium">Date range</span>
            <Select value={dateRange} onValueChange={(v) => setDateRange(v as DateRangeKey)}>
              <SelectTrigger className="w-[160px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(DATE_RANGES) as DateRangeKey[]).map((key) => (
                  <SelectItem key={key} value={key}>
                    {DATE_RANGES[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button onClick={() => void handleCreate()} disabled={isCreating}>
            {isCreating ? "Creating export..." : "Create Export"}
          </Button>
        </CardContent>
      </Card>

      {isLoading ? (
        <TableSkeleton rows={3} columns={6} />
      ) : exports.length === 0 ? (
        <EmptyState
          title="No exports yet"
          description="Create your first export above to download your memories."
        />
      ) : (
        <Card className="border-memBorder-primary overflow-hidden">
          <DataTable data={exports} columns={columns} getRowKey={(row) => row.id} />
        </Card>
      )}

      <DeleteConfirmationModal
        isOpen={!!exportToDelete}
        onClose={() => setExportToDelete(null)}
        onConfirm={handleDelete}
        title="Delete export"
        description="This export's history record will be permanently removed. This cannot be undone."
        itemName={exportToDelete ? `${exportToDelete.format.toUpperCase()} export` : ""}
        confirmButtonText="Delete"
      />
    </div>
  );
}
