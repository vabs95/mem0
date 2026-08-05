"use client";

import { useEffect, useState } from "react";
import { GitCompare, ShieldAlert, CheckCircle2, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Memory } from "@/types/api";

export default function ContradictionsPage() {
  const [memories, setMemories] = useState<Memory[]>([]);

  const { data: rawMemories = [], isLoading, refetch } = useApiQuery<Memory[]>(
    async () => {
      const res = await api.get(MEMORY_ENDPOINTS.BASE, { params: { top_k: 500 } });
      const raw = res.data?.results ?? res.data ?? [];
      return Array.isArray(raw) ? raw : [];
    },
    { errorToast: "Failed to load memories", initialData: [] },
  );

  const supersededMemories = rawMemories.filter(
    (m: any) => m.status === "superseded" || m.metadata?.status === "superseded"
  );
  const activeCount = rawMemories.length - supersededMemories.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold font-fustat flex items-center gap-2">
            <GitCompare className="size-5 text-memGold-500" />
            Contradictions & Supersede Lifecycle
          </h1>
          <p className="text-sm text-onSurface-default-tertiary mt-1">
            Mem0 automatically detects contradictory facts (vector similarity ≥ 0.85) within tenant scope and marks older memories as superseded.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
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
          description="When new contradictory facts are ingested into Mem0, older vector-similar facts will be automatically linked and archived here."
        />
      ) : (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-onSurface-default-tertiary">
            Superseded Memory Lineage Chains ({supersededMemories.length})
          </h2>
          {supersededMemories.map((mem: any) => (
            <Card key={mem.id} className="p-4 border-memBorder-primary space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="border-amber-500 text-amber-500">
                    <ShieldAlert className="size-3 mr-1" />
                    Superseded
                  </Badge>
                  {mem.category && (
                    <Badge variant="outline" className="capitalize">
                      {mem.category}
                    </Badge>
                  )}
                  {mem.importance && (
                    <Badge variant="outline">
                      Importance: {mem.importance}/10
                    </Badge>
                  )}
                </div>
                <span className="text-xs font-mono text-onSurface-default-tertiary">
                  ID: {mem.id}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-surface-default-secondary p-3 rounded-lg text-sm">
                <div>
                  <p className="text-xs text-onSurface-default-tertiary font-semibold mb-1">Outdated Fact (Hidden from Search)</p>
                  <p className="line-through text-onSurface-default-tertiary">{mem.memory || mem.data}</p>
                </div>
                {mem.superseded_by_id && (
                  <div className="border-t md:border-t-0 md:border-l border-memBorder-primary pt-2 md:pt-0 md:pl-4">
                    <p className="text-xs text-emerald-500 font-semibold mb-1 flex items-center gap-1">
                      <CheckCircle2 className="size-3" />
                      Superseded By Memory
                    </p>
                    <p className="font-mono text-xs text-onSurface-default-primary break-all">{mem.superseded_by_id}</p>
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
