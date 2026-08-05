"use client";

import { useMemo, useState } from "react";
import { Search, Trash2 } from "lucide-react";
import { format } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, EntityType } from "@/types/api";

const TYPE_PILLS: { value: EntityType | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "user", label: "User" },
  { value: "agent", label: "Agent" },
  { value: "run", label: "Run" },
  { value: "project", label: "Project" },
];

export default function EntitiesPage() {
  const [entityToDelete, setEntityToDelete] = useState<Entity | null>(null);
  const [typeFilter, setTypeFilter] = useState<EntityType | "all">("all");
  const [search, setSearch] = useState("");

  const {
    data: entities = [],
    isLoading,
    refetch,
  } = useApiQuery<Entity[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load entities", initialData: [] },
  );

  const filteredEntities = useMemo(() => {
    const query = search.trim().toLowerCase();
    return entities.filter((e) => {
      if (typeFilter !== "all" && e.type !== typeFilter) return false;
      if (query && !e.id.toLowerCase().includes(query)) return false;
      return true;
    });
  }, [entities, typeFilter, search]);

  const hasActiveFilters = typeFilter !== "all" || search.trim() !== "";

  const handleDelete = async () => {
    if (!entityToDelete) return;
    try {
      await api.delete(
        ENTITY_ENDPOINTS.BY_ID(entityToDelete.type, entityToDelete.id),
      );
      toast({ title: "Entity deleted", variant: "success" });
      setEntityToDelete(null);
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to delete entity",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    }
  };

  const columns = [
    {
      key: "type" as keyof Entity,
      label: "Type",
      width: 100,
      render: (value: Entity["type"]) => (
        <Badge variant="outline" className="capitalize">
          {value}
        </Badge>
      ),
    },
    {
      key: "id" as keyof Entity,
      label: "ID",
      width: 280,
      render: (value: string) => (
        <span className="font-mono text-sm truncate">{value}</span>
      ),
    },
    {
      key: "total_memories" as keyof Entity,
      label: "Memories",
      width: 100,
      align: "right" as const,
    },
    {
      key: "updated_at" as keyof Entity,
      label: "Last Active",
      width: 140,
      render: (value: string | null) =>
        value ? format(new Date(value), "MMM d, yyyy") : "--",
    },
    {
      key: "id" as keyof Entity,
      label: "",
      width: 40,
      render: (_: string, row: Entity) => (
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setEntityToDelete(row)}
          className="size-7"
        >
          <Trash2 className="size-3.5 text-onSurface-danger-primary" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold font-fustat">Entities</h1>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-onSurface-default-tertiary" />
            <Input
              placeholder="Search entity ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setTypeFilter("all");
                setSearch("");
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {TYPE_PILLS.map((pill) => (
            <button
              key={pill.value}
              onClick={() => setTypeFilter(pill.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                typeFilter === pill.value
                  ? "border-onSurface-default-primary bg-onSurface-default-primary text-surface-default-primary"
                  : "border-memBorder-primary text-onSurface-default-secondary hover:bg-surface-default-secondary",
              )}
            >
              {pill.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton rows={5} columns={5} />
      ) : filteredEntities.length === 0 ? (
        <EmptyState
          title="No entities yet"
          description={
            hasActiveFilters
              ? "No entities match the current filters."
              : "Entities appear once memories are stored with a user_id, agent_id, run_id, or project."
          }
        />
      ) : (
        <Card className="border-memBorder-primary overflow-hidden">
          <DataTable
            data={filteredEntities}
            columns={columns}
            getRowKey={(row) => `${row.type}:${row.id}`}
          />
        </Card>
      )}

      <DeleteConfirmationModal
        isOpen={!!entityToDelete}
        onClose={() => setEntityToDelete(null)}
        onConfirm={handleDelete}
        title="Delete entity"
        description="All memories associated with this entity will be permanently removed. This cannot be undone."
        itemName={entityToDelete?.id ?? ""}
        confirmButtonText="Delete"
      />
    </div>
  );
}
