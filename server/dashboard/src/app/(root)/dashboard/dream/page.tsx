"use client";

import { useState } from "react";
import { Sparkles, Play, CheckCircle2, Layers, RefreshCw } from "lucide-react";
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
import { toast } from "@/components/ui/use-toast";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity } from "@/types/api";
import { isAxiosError } from "axios";

interface DreamResult {
  processed?: number;
  clusters_merged?: number;
  new_memories_created?: number;
  memories_merged?: number;
}

const ALL_VALUES = "__all__";

export default function DreamPage() {
  const [userId, setUserId] = useState(ALL_VALUES);
  const [projectId, setProjectId] = useState(ALL_VALUES);
  const [similarityThreshold, setSimilarityThreshold] = useState("0.90");
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState<DreamResult | null>(null);
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

  // 'project' alone can't own the synthesized memory dream() creates for a
  // merge cluster -- the backend requires user_id/agent_id/run_id (project
  // only narrows scope within that). This page only exposes a user selector,
  // so that's the one required field.
  const hasScope = userId !== ALL_VALUES;

  const handleTriggerDream = async () => {
    setConfirmOpen(false);
    setRunning(true);
    setLastResult(null);
    try {
      const res = await api.post(MEMORY_ENDPOINTS.DREAM, {
        user_id: userId === ALL_VALUES ? undefined : userId,
        project: projectId === ALL_VALUES ? undefined : projectId,
        similarity_threshold: parseFloat(similarityThreshold) || 0.90,
        limit: 100,
      });
      setLastResult(res.data);
      toast({
        title: "Dream Consolidation Complete",
        description: `Processed ${res.data?.processed || 0} facts, merged ${res.data?.clusters_merged || 0} clusters into synthesized memories.`,
        variant: "success",
      });
    } catch (err: unknown) {
      const message = isAxiosError(err) ? err.response?.data?.detail || err.message : "Upstream error";
      toast({
        title: "Dream Consolidation Failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat flex items-center gap-2">
          <Sparkles className="size-5 text-purple-400" />
          Dream Memory Consolidation Engine
        </h1>
        <p className="text-sm text-onSurface-default-tertiary mt-1">
          Scans active memories within tenant scope, clusters near-duplicate facts (similarity ≥ 0.90), and synthesizes them into consolidated memory statements while updating merged source status.
        </p>
      </div>

      <Card className="p-5 border-memBorder-primary space-y-4">
        <h2 className="text-sm font-semibold">Run Consolidation Pass</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
            owner, so a project alone isn&apos;t enough. Add a project too to narrow the scope
            further within that user.
          </p>
        )}

        <Button
          onClick={() => setConfirmOpen(true)}
          disabled={running || !hasScope}
          className="gap-2 bg-purple-600 hover:bg-purple-700"
        >
          {running ? <RefreshCw className="size-4 animate-spin" /> : <Play className="size-4" />}
          {running ? "Consolidating Facts..." : "Trigger Dream Consolidation"}
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

      {lastResult && (
        <Card className="p-5 border-purple-500/30 bg-purple-500/5 space-y-4">
          <div className="flex items-center gap-2 text-purple-400 font-semibold text-sm">
            <CheckCircle2 className="size-4" />
            Consolidation Summary
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-surface-default-secondary p-3 rounded">
              <span className="text-onSurface-default-tertiary block">Active Facts Scanned</span>
              <span className="text-lg font-bold font-mono">{lastResult.processed || 0}</span>
            </div>
            <div className="bg-surface-default-secondary p-3 rounded">
              <span className="text-onSurface-default-tertiary block">Clusters Merged</span>
              <span className="text-lg font-bold font-mono text-purple-400">{lastResult.clusters_merged || 0}</span>
            </div>
            <div className="bg-surface-default-secondary p-3 rounded">
              <span className="text-onSurface-default-tertiary block">Synthesized Memories</span>
              <span className="text-lg font-bold font-mono text-emerald-400">{lastResult.new_memories_created || 0}</span>
            </div>
            <div className="bg-surface-default-secondary p-3 rounded">
              <span className="text-onSurface-default-tertiary block">Source Facts Merged</span>
              <span className="text-lg font-bold font-mono text-amber-400">{lastResult.memories_merged || 0}</span>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
