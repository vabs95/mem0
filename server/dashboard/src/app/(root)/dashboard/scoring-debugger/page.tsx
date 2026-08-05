"use client";

import { useState } from "react";
import { Brain, Search, Sparkles, SlidersHorizontal, Calculator } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { Memory } from "@/types/api";

interface ScoreDetails {
  semantic_score?: number;
  bm25_score?: number;
  entity_boost?: number;
  importance_score?: number;
  recency_score?: number;
  raw_score?: number;
  max_possible_score?: number;
  final_score?: number;
  threshold?: number;
}

interface ScoredMemory extends Memory {
  score?: number;
  score_details?: ScoreDetails;
}

export default function ScoringDebuggerPage() {
  const [query, setQuery] = useState("");
  const [userId, setUserId] = useState("");
  const [results, setResults] = useState<ScoredMemory[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await api.post(MEMORY_ENDPOINTS.SEARCH, {
        query: query.trim(),
        filters: userId.trim() ? { user_id: userId.trim() } : {},
        top_k: 10,
        explain: true,
      });
      const data = res.data?.results ?? res.data ?? [];
      setResults(Array.isArray(data) ? data : []);
    } catch (err) {
      toast({
        title: "Search Calculation Failed",
        description: getErrorMessage(err, "Failed to compute scores"),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold font-fustat flex items-center gap-2">
          <Brain className="size-5 text-indigo-400" />
          Hybrid Scoring Debugger & Formula Inspector
        </h1>
        <p className="text-sm text-onSurface-default-tertiary mt-1">
          Test search queries to inspect the hybrid mathematical ranking formula:
          <code className="text-xs ml-1 bg-surface-default-secondary px-1.5 py-0.5 rounded font-mono">
            FinalScore = (VectorSim + BM25 + EntityBoost + 0.3*Importance + 0.2*Recency) / MaxPossible
          </code>
        </p>
      </div>

      <Card className="p-4 border-memBorder-primary space-y-4">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 size-4 text-onSurface-default-tertiary" />
            <Input
              placeholder="Enter search query to debug scores (e.g. 'authentication preferences')..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-9"
            />
          </div>
          <Input
            placeholder="User ID filter (optional)"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-full sm:w-48"
          />
          <Button onClick={handleSearch} disabled={loading} className="gap-2">
            <Calculator className="size-4" />
            Calculate Scores
          </Button>
        </div>
      </Card>

      {loading ? (
        <TableSkeleton rows={3} columns={4} />
      ) : results.length > 0 ? (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-onSurface-default-tertiary">
            Ranked Candidate Results ({results.length})
          </h2>
          {results.map((item, idx) => {
            const score = item.score ?? 0.0;
            const details = item.score_details || {};
            const importance = item.metadata?.importance ?? 5;
            const category = item.metadata?.category ?? "general";

            return (
              <Card key={item.id || idx} className="p-4 border-memBorder-primary space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="font-mono bg-surface-default-tertiary">
                      Rank #{idx + 1}
                    </Badge>
                    <Badge className="bg-indigo-600 font-mono">
                      Score: {(score * 100).toFixed(1)}%
                    </Badge>
                    <Badge variant="outline" className="capitalize">
                      Category: {category}
                    </Badge>
                    <Badge variant="outline">
                      Importance: {importance}/10
                    </Badge>
                  </div>
                  <span className="text-xs font-mono text-onSurface-default-tertiary">
                    ID: {item.id}
                  </span>
                </div>

                <p className="text-sm font-medium">{item.memory}</p>

                {/* Score Breakdown Pills */}
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-2 border-t border-memBorder-primary text-xs">
                  <div className="bg-surface-default-secondary p-2 rounded">
                    <span className="text-onSurface-default-tertiary block">Vector Sim (1.0x)</span>
                    <span className="font-mono font-bold text-indigo-400">
                      {details.semantic_score ? (details.semantic_score * 100).toFixed(1) + "%" : "0.0%"}
                    </span>
                  </div>
                  <div className="bg-surface-default-secondary p-2 rounded">
                    <span className="text-onSurface-default-tertiary block">BM25 Rank (1.0x)</span>
                    <span className="font-mono font-bold text-sky-400">
                      {details.bm25_score ? (details.bm25_score * 100).toFixed(1) + "%" : "N/A"}
                    </span>
                  </div>
                  <div className="bg-surface-default-secondary p-2 rounded">
                    <span className="text-onSurface-default-tertiary block">Entity Boost (0.5x)</span>
                    <span className="font-mono font-bold text-amber-400">
                      {details.entity_boost ? (details.entity_boost * 100).toFixed(1) + "%" : "0.0%"}
                    </span>
                  </div>
                  <div className="bg-surface-default-secondary p-2 rounded">
                    <span className="text-onSurface-default-tertiary block">Importance (0.3x)</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {importance}/10
                    </span>
                  </div>
                  <div className="bg-surface-default-secondary p-2 rounded">
                    <span className="text-onSurface-default-tertiary block">Recency Decay (0.2x)</span>
                    <span className="font-mono font-bold text-rose-400">
                      {details.recency_score ? (details.recency_score * 100).toFixed(1) + "%" : "100%"}
                    </span>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card className="p-8 text-center text-onSurface-default-tertiary border-memBorder-primary">
          <SlidersHorizontal className="size-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Type a search query above to debug score formulas and candidate weights.</p>
        </Card>
      )}
    </div>
  );
}
