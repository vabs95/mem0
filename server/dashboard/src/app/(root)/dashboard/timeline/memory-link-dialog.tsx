"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import { ArrowLeft } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { Memory } from "@/types/api";

type FetchStatus = "loading" | "success" | "notfound" | "error";

interface MemoryLinkDialogProps {
  memoryIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function MemoryDetail({ memory }: { memory: Memory }) {
  const category = memory.metadata?.category;
  const importance = memory.metadata?.importance;
  const project = memory.metadata?.project;

  return (
    <div className="space-y-3">
      <p className="text-sm text-onSurface-default-primary whitespace-pre-wrap">
        {memory.memory}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {category && (
          <Badge
            variant="outline"
            className="px-1.5 py-0 text-[10px] capitalize"
          >
            {category.replace(/_/g, " ")}
          </Badge>
        )}
        {typeof importance === "number" && (
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            Importance {importance}
          </Badge>
        )}
        {typeof project === "string" && (
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            {project}
          </Badge>
        )}
      </div>
    </div>
  );
}

export function MemoryLinkDialog({
  memoryIds,
  open,
  onOpenChange,
}: MemoryLinkDialogProps) {
  const [results, setResults] = useState<
    Record<string, { status: FetchStatus; memory?: Memory }>
  >(() =>
    Object.fromEntries(
      memoryIds.map((id) => [id, { status: "loading" as FetchStatus }]),
    ),
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    memoryIds.length === 1 ? memoryIds[0] : null,
  );

  useEffect(() => {
    let cancelled = false;
    memoryIds.forEach((id) => {
      api
        .get<Memory>(MEMORY_ENDPOINTS.BY_ID(id))
        .then((res) => {
          if (cancelled) return;
          setResults((prev) => ({
            ...prev,
            [id]: { status: "success", memory: res.data },
          }));
        })
        .catch((err) => {
          if (cancelled) return;
          const status: FetchStatus =
            axios.isAxiosError(err) && err.response?.status === 404
              ? "notfound"
              : "error";
          setResults((prev) => ({ ...prev, [id]: { status } }));
        });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = selectedId ? results[selectedId] : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {memoryIds.length === 1 ? "Linked memory" : "Linked memories"}
          </DialogTitle>
        </DialogHeader>

        {selectedId ? (
          <div className="space-y-3">
            {memoryIds.length > 1 && (
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="flex items-center gap-1 text-xs text-onSurface-default-secondary hover:text-onSurface-default-primary"
              >
                <ArrowLeft className="size-3.5" />
                Back to list
              </button>
            )}
            {!selected || selected.status === "loading" ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ) : selected.status === "notfound" ? (
              <p className="text-sm text-onSurface-default-tertiary italic">
                Memory no longer exists.
              </p>
            ) : selected.status === "error" ? (
              <p className="text-sm text-destructive">
                Failed to load this memory.
              </p>
            ) : (
              <MemoryDetail memory={selected.memory!} />
            )}
          </div>
        ) : (
          <div className="space-y-1 max-h-80 overflow-y-auto">
            {memoryIds.map((id) => {
              const entry = results[id];
              return (
                <button
                  key={id}
                  type="button"
                  disabled={!entry || entry.status !== "success"}
                  onClick={() => setSelectedId(id)}
                  className="w-full text-left rounded-md border border-memBorder-primary p-2 hover:bg-surface-default-secondary/40 disabled:cursor-default disabled:hover:bg-transparent transition-colors"
                >
                  {!entry || entry.status === "loading" ? (
                    <Skeleton className="h-4 w-full" />
                  ) : entry.status === "notfound" ? (
                    <p className="text-xs text-onSurface-default-tertiary italic">
                      Memory no longer exists ({id.slice(0, 8)})
                    </p>
                  ) : entry.status === "error" ? (
                    <p className="text-xs text-destructive">
                      Failed to load ({id.slice(0, 8)})
                    </p>
                  ) : (
                    <div className="space-y-1">
                      <p className="text-xs text-onSurface-default-primary line-clamp-1">
                        {entry.memory!.memory}
                      </p>
                      {entry.memory!.metadata?.category && (
                        <Badge
                          variant="outline"
                          className="px-1.5 py-0 text-[10px] capitalize"
                        >
                          {entry.memory!.metadata.category.replace(/_/g, " ")}
                        </Badge>
                      )}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
