"use client";

import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Sparkles, Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
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
import { toast } from "@/components/ui/use-toast";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { cn } from "@/lib/utils";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { DreamRun, Entity } from "@/types/api";
import { getErrorMessage } from "@/lib/error-message";

const ALL_VALUES = "__all__";
const POLL_INTERVAL_MS = 2000;

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  failed: "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  running: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

function scopeLabel(run: DreamRun): string {
  const parts = [
    run.user_id && `user=${run.user_id}`,
    run.agent_id && `agent=${run.agent_id}`,
    run.run_id && `run=${run.run_id}`,
    run.project && `project=${run.project}`,
  ].filter(Boolean);
  return parts.join(" ");
}

export default function DreamPage() {
  const [userId, setUserId] = useState(ALL_VALUES);
  const [agentId, setAgentId] = useState(ALL_VALUES);
  const [runId, setRunId] = useState(ALL_VALUES);
  const [projectId, setProjectId] = useState(ALL_VALUES);
  const [similarityThreshold, setSimilarityThreshold] = useState("0.90");
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { data: entities = [] } = useApiQuery<Entity[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load entities", initialData: [] },
  );
  const byType = (type: Entity["type"]) =>
    entities.filter((e) => e.type === type).map((e) => e.id).sort();

  // hasRunningRun lags one render behind `runs` (updated via the effect
  // below rather than computed inline) since it feeds back into this same
  // query's refetchInterval option -- the hook can't read its own
  // not-yet-returned result within the call that produces it, but the
  // effect + re-render loop achieves the same thing: once a fetch comes
  // back with a "running" row, the next render passes a real interval and
  // the hook's polling effect re-subscribes. No polling once nothing in the
  // history is "running".
  const [hasRunningRun, setHasRunningRun] = useState(false);
  const { data: runs = [], isLoading, refetch } = useApiQuery<DreamRun[]>(
    async () => {
      const res = await api.get<DreamRun[]>(MEMORY_ENDPOINTS.DREAM_RUNS);
      return res.data ?? [];
    },
    {
      errorToast: "Failed to load Dream run history",
      initialData: [],
      refetchInterval: hasRunningRun ? POLL_INTERVAL_MS : undefined,
    },
  );
  useEffect(() => {
    setHasRunningRun(runs.some((r) => r.status === "running"));
  }, [runs]);

  // 'project' alone can't own the synthesized memory dream() creates for a
  // merge cluster -- the backend requires user_id/agent_id/run_id. This page
  // requires a user; agent/run/project are optional additional narrowing.
  const hasScope = userId !== ALL_VALUES;

  const nullSafe = (v: string) => (v === ALL_VALUES ? null : v);
  const isSelectedScopeRunning = runs.some(
    (r) =>
      r.status === "running" &&
      (r.user_id ?? null) === nullSafe(userId) &&
      (r.agent_id ?? null) === nullSafe(agentId) &&
      (r.run_id ?? null) === nullSafe(runId) &&
      (r.project ?? null) === nullSafe(projectId),
  );

  const handleTriggerDream = async () => {
    setConfirmOpen(false);
    setSubmitting(true);
    try {
      await api.post(MEMORY_ENDPOINTS.DREAM, {
        user_id: userId === ALL_VALUES ? undefined : userId,
        agent_id: agentId === ALL_VALUES ? undefined : agentId,
        run_id: runId === ALL_VALUES ? undefined : runId,
        project: projectId === ALL_VALUES ? undefined : projectId,
        similarity_threshold: parseFloat(similarityThreshold) || 0.90,
        limit: 100,
      });
      toast({
        title: "Dream Consolidation Started",
        description: "Running in the background -- this page updates automatically as it progresses.",
        variant: "success",
      });
      void refetch();
    } catch (err) {
      toast({
        title: "Dream Consolidation Failed to Start",
        description: getErrorMessage(err, "Upstream error"),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      key: "status" as keyof DreamRun,
      label: "Status",
      width: 100,
      render: (value: string) => (
        <Badge
          variant="outline"
          className={cn("px-1.5 py-0 text-[10px] capitalize border-0", STATUS_BADGE[value])}
        >
          {value === "running" && <RefreshCw className="size-2.5 mr-1 animate-spin" />}
          {value}
        </Badge>
      ),
    },
    {
      key: "user_id" as keyof DreamRun,
      label: "Scope",
      width: 260,
      render: (_: string, row: DreamRun) => (
        <span className="text-xs font-mono truncate">{scopeLabel(row) || "--"}</span>
      ),
    },
    {
      key: "processed" as keyof DreamRun,
      label: "Scanned",
      width: 80,
    },
    {
      key: "clusters_merged" as keyof DreamRun,
      label: "Clusters",
      width: 80,
    },
    {
      key: "new_memories_created" as keyof DreamRun,
      label: "Synthesized",
      width: 90,
    },
    {
      key: "memories_merged" as keyof DreamRun,
      label: "Merged",
      width: 80,
    },
    {
      key: "created_at" as keyof DreamRun,
      label: "Started",
      width: 140,
      render: (value: string) => format(new Date(value), "MMM d, yyyy HH:mm"),
    },
    {
      key: "completed_at" as keyof DreamRun,
      label: "Finished",
      width: 140,
      render: (value: string | null) => (value ? format(new Date(value), "MMM d, yyyy HH:mm") : "--"),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat flex items-center gap-2">
          <Sparkles className="size-5 text-purple-400" />
          Dream Memory Consolidation Engine
        </h1>
        <p className="text-sm text-onSurface-default-tertiary mt-1">
          Scans active memories within tenant scope, clusters near-duplicate facts (similarity ≥ 0.90), and synthesizes them into consolidated memory statements while updating merged source status. Runs in the background -- history below persists across refreshes.
        </p>
      </div>

      <Card className="p-5 border-memBorder-primary space-y-4">
        <h2 className="text-sm font-semibold">Run Consolidation Pass</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <Select value={userId} onValueChange={setUserId}>
            <SelectTrigger>
              <SelectValue placeholder="Select a user (required)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUES} disabled>
                Select a user (required)
              </SelectItem>
              {byType("user").map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={agentId} onValueChange={setAgentId}>
            <SelectTrigger>
              <SelectValue placeholder="Narrow to an agent (optional)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUES}>All agents for this user</SelectItem>
              {byType("agent").map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={runId} onValueChange={setRunId}>
            <SelectTrigger>
              <SelectValue placeholder="Narrow to a run (optional)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUES}>All runs for this user</SelectItem>
              {byType("run").map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger>
              <SelectValue placeholder="Narrow to a project (optional)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUES}>All projects for this user</SelectItem>
              {byType("project").map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            placeholder="Similarity Threshold (default: 0.90)"
            value={similarityThreshold}
            onChange={(e) => setSimilarityThreshold(e.target.value)}
          />
        </div>
        {!hasScope && (
          <p className="text-xs text-onSurface-danger-primary">
            Select a user -- the synthesized memory Dream creates for each merge cluster needs an
            owner, so agent/run/project alone aren&apos;t enough. They narrow the scope further
            once a user is selected.
          </p>
        )}
        {hasScope && isSelectedScopeRunning && (
          <p className="text-xs text-onSurface-default-tertiary">
            A Dream run is already in progress for this exact scope -- wait for it to finish
            before starting another.
          </p>
        )}

        <Button
          onClick={() => setConfirmOpen(true)}
          disabled={submitting || !hasScope || isSelectedScopeRunning}
          className="gap-2 bg-purple-600 hover:bg-purple-700"
        >
          {submitting ? <RefreshCw className="size-4 animate-spin" /> : <Play className="size-4" />}
          {submitting ? "Starting..." : "Start Dream Consolidation"}
        </Button>
      </Card>

      <DeleteConfirmationModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={handleTriggerDream}
        title="Run Dream Consolidation"
        description="This merges near-duplicate active memories within the selected scope into synthesized memories and marks their sources as merged. This cannot be undone from the dashboard."
        itemName="CONSOLIDATE"
        confirmButtonText="Run Consolidation"
      />

      <div className="space-y-2">
        <h2 className="text-sm font-medium text-onSurface-default-tertiary">
          Run History {hasRunningRun && "(live)"}
        </h2>
        {isLoading ? (
          <TableSkeleton rows={3} columns={8} />
        ) : runs.length === 0 ? (
          <EmptyState
            title="No Dream runs yet"
            description="Runs you start above will appear here and update automatically until they finish."
          />
        ) : (
          <Card className="border-memBorder-primary overflow-hidden">
            <DataTable data={runs} columns={columns} getRowKey={(row) => row.id} />
          </Card>
        )}
      </div>
    </div>
  );
}
