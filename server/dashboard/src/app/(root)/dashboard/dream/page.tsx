"use client";

import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Sparkles, Play, RefreshCw, ShieldAlert, CheckCircle2, Layers } from "lucide-react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { toast } from "@/components/ui/use-toast";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { cn } from "@/lib/utils";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { DreamRun, Entity, Memory } from "@/types/api";
import { getErrorMessage } from "@/lib/error-message";

const ALL_VALUES = "__all__";
const POLL_INTERVAL_MS = 2000;

type DreamTab = "synthesis" | "supersede" | "merge";

function initialTab(): DreamTab {
  if (typeof window === "undefined") return "merge";
  const fromQuery = new URLSearchParams(window.location.search).get("tab");
  return fromQuery === "synthesis" || fromQuery === "supersede" ? fromQuery : "merge";
}

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  failed: "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  running: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

const TAB_STATUS_BADGE: Record<DreamTab, string> = {
  synthesis: "text-onSurface-default-tertiary border-memBorder-primary",
  supersede: "text-emerald-600 border-emerald-300 dark:text-emerald-300 dark:border-emerald-800",
  merge: "text-amber-600 border-amber-300 dark:text-amber-300 dark:border-amber-800",
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
  const [activeTab, setActiveTab] = useState<DreamTab>(initialTab);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat flex items-center gap-2">
          <Sparkles className="size-5 text-purple-400" />
          Dream
        </h1>
        <p className="text-sm text-onSurface-default-tertiary mt-1">
          Background curation that keeps memories current -- Synthesis, Supersede, and Merge.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as DreamTab)}>
        <TabsList>
          <TabsTrigger value="synthesis" className="gap-1.5">
            Synthesis
            <Badge variant="outline" className={cn("px-1.5 py-0 text-[10px] border", TAB_STATUS_BADGE.synthesis)}>
              Not built
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="supersede" className="gap-1.5">
            Supersede
            <Badge variant="outline" className={cn("px-1.5 py-0 text-[10px] border", TAB_STATUS_BADGE.supersede)}>
              Always on
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="merge" className="gap-1.5">
            Merge
            <Badge variant="outline" className={cn("px-1.5 py-0 text-[10px] border", TAB_STATUS_BADGE.merge)}>
              Manual
            </Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="synthesis">
          <SynthesisTab />
        </TabsContent>
        <TabsContent value="supersede">
          <SupersedeTab />
        </TabsContent>
        <TabsContent value="merge">
          <MergeTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SynthesisTab() {
  return (
    <Card className="p-6 border-memBorder-primary space-y-3 text-center">
      <Layers className="size-8 mx-auto text-onSurface-default-tertiary" />
      <h2 className="text-sm font-semibold">Recurring signals become pattern memories</h2>
      <p className="text-sm text-onSurface-default-tertiary max-w-lg mx-auto">
        Not built yet. Synthesis would detect a recurring signal across multiple related (not just
        near-duplicate) memories over time and generate a higher-level pattern memory from them --
        a genuinely different capability from Merge, which only folds near-identical facts into one.
        See the Roadmap section of <code className="text-xs">ARCHITECTURE.md</code> for more.
      </p>
    </Card>
  );
}

function SupersedeTab() {
  const { data: rawMemories = [], isLoading, refetch } = useApiQuery<Memory[]>(
    async () => {
      // show_superseded=true is required here -- GET /memories excludes
      // superseded/merged memories by default (same convention as
      // show_expired), so without it this tab could never see the data
      // it exists to display.
      const res = await api.get(MEMORY_ENDPOINTS.BASE, { params: { top_k: 500, show_superseded: true } });
      const raw = res.data?.results ?? res.data ?? [];
      return Array.isArray(raw) ? raw : [];
    },
    { errorToast: "Failed to load memories", initialData: [] },
  );

  const supersededMemories = rawMemories.filter((m) => m.metadata?.status === "superseded");
  const activeCount = rawMemories.length - supersededMemories.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-onSurface-default-tertiary">
          Runs automatically on every new memory -- flags candidates by vector similarity (&ge; 0.85),
          then asks the LLM to confirm before marking the older memory superseded. Similarity alone
          never hides a memory.
        </p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} className="shrink-0 ml-4">
          Refresh Lineage
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 border-memBorder-primary">
          <p className="text-xs text-onSurface-default-tertiary font-medium">Total Indexed Facts</p>
          <p className="text-2xl font-bold mt-1 font-mono">{rawMemories.length}</p>
        </Card>
        <Card className="p-4 border-memBorder-primary">
          <p className="text-xs text-onSurface-default-tertiary font-medium">Active Valid Facts</p>
          <p className="text-2xl font-bold mt-1 text-emerald-500 font-mono">{activeCount}</p>
        </Card>
        <Card className="p-4 border-memBorder-primary">
          <p className="text-xs text-onSurface-default-tertiary font-medium">Superseded Contradictions</p>
          <p className="text-2xl font-bold mt-1 text-amber-500 font-mono">{supersededMemories.length}</p>
        </Card>
      </div>

      {isLoading ? (
        <TableSkeleton rows={4} columns={3} />
      ) : supersededMemories.length === 0 ? (
        <EmptyState
          title="No Contradictions Detected"
          description="When new contradictory facts are ingested into Mem0, older vector-similar facts confirmed as contradictions will be linked and archived here."
        />
      ) : (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-onSurface-default-tertiary">
            Superseded Memory Lineage Chains ({supersededMemories.length})
          </h2>
          {supersededMemories.map((mem) => (
            <Card key={mem.id} className="p-4 border-memBorder-primary space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="border-amber-500 text-amber-500">
                    <ShieldAlert className="size-3 mr-1" />
                    Superseded
                  </Badge>
                  {mem.metadata?.category && (
                    <Badge variant="outline" className="capitalize">
                      {mem.metadata.category}
                    </Badge>
                  )}
                  {mem.metadata?.importance != null && (
                    <Badge variant="outline">Importance: {mem.metadata.importance}/10</Badge>
                  )}
                </div>
                <span className="text-xs font-mono text-onSurface-default-tertiary">ID: {mem.id}</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-surface-default-secondary p-3 rounded-lg text-sm">
                <div>
                  <p className="text-xs text-onSurface-default-tertiary font-semibold mb-1">
                    Outdated Fact (Hidden from Search)
                  </p>
                  <p className="line-through text-onSurface-default-tertiary">{mem.memory}</p>
                </div>
                {mem.metadata?.superseded_by_id && (
                  <div className="border-t md:border-t-0 md:border-l border-memBorder-primary pt-2 md:pt-0 md:pl-4">
                    <p className="text-xs text-emerald-500 font-semibold mb-1 flex items-center gap-1">
                      <CheckCircle2 className="size-3" />
                      Superseded By Memory
                    </p>
                    <p className="font-mono text-xs text-onSurface-default-primary break-all">
                      {mem.metadata.superseded_by_id}
                    </p>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function MergeTab() {
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
      <Card className="p-5 border-memBorder-primary space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Run Consolidation Pass</h2>
          <p className="text-xs text-onSurface-default-tertiary mt-1">
            Clusters near-duplicate active memories (similarity &ge; 0.90) within the selected scope
            and folds each cluster into one synthesized memory. Manual/on-demand -- runs in the
            background once started, history below persists across refreshes.
          </p>
        </div>
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
