"use client";

import { useState } from "react";
import { Sparkles, Play, CheckCircle2, Layers, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/use-toast";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { isAxiosError } from "axios";

interface DreamResult {
  processed?: number;
  clusters_merged?: number;
  new_memories_created?: number;
  memories_merged?: number;
}

export default function DreamPage() {
  const [userId, setUserId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [similarityThreshold, setSimilarityThreshold] = useState("0.90");
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState<DreamResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleTriggerDream = async () => {
    setConfirmOpen(false);
    setRunning(true);
    setLastResult(null);
    try {
      const res = await api.post(MEMORY_ENDPOINTS.DREAM, {
        user_id: userId.trim() || undefined,
        project: projectId.trim() || undefined,
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
          <Input
            placeholder="User ID (optional)"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          />
          <Input
            placeholder="Project ID (optional)"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          />
          <Input
            placeholder="Similarity Threshold (default: 0.90)"
            value={similarityThreshold}
            onChange={(e) => setSimilarityThreshold(e.target.value)}
          />
        </div>

        <Button
          onClick={() => setConfirmOpen(true)}
          disabled={running}
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
