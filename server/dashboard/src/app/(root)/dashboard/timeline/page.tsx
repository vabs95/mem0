"use client";

import { useEffect, useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, TIMELINE_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, TimelineEvent } from "@/types/api";

const EVENT_LIMIT = 100;
const ALL_PROJECTS = "__all__";

const getEventTypeClassName = (eventType: string) => {
  switch (eventType) {
    case "session_start":
      return "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-950/40 dark:text-sky-300";
    case "add_memory":
      return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/40 dark:text-emerald-300";
    case "delete_all":
      return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-300";
    default:
      return "border-memBorder-primary bg-surface-default-secondary text-onSurface-default-secondary";
  }
};

const scopeLabel = (event: TimelineEvent): string => {
  const parts: string[] = [];
  if (event.user_id) parts.push(event.user_id);
  if (event.agent_id) parts.push(event.agent_id);
  if (event.project) parts.push(event.project);
  if (event.run_id) parts.push(event.run_id);
  return parts.join(" · ") || "--";
};

export default function TimelinePage() {
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<string>(ALL_PROJECTS);

  const { data: projects = [] } = useApiQuery<string[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return (res.data ?? [])
        .filter((entity) => entity.type === "project")
        .map((entity) => entity.id)
        .sort();
    },
    { errorToast: "Failed to load projects", initialData: [] },
  );

  const {
    data: events = [],
    isLoading,
    refetch,
  } = useApiQuery<TimelineEvent[]>(
    async () => {
      const res = await api.get<TimelineEvent[]>(TIMELINE_ENDPOINTS.EVENTS, {
        params: {
          limit: EVENT_LIMIT,
          project: selectedProject === ALL_PROJECTS ? undefined : selectedProject,
        },
      });
      setLastUpdated(new Date().toISOString());
      return res.data ?? [];
    },
    { errorToast: "Failed to load timeline", initialData: [] },
  );

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    void refetch();
  }, [selectedProject]);

  const columns = [
    {
      key: "created_at" as keyof TimelineEvent,
      label: "Time",
      width: 140,
      render: (value: string) => (
        <span title={format(new Date(value), "PPpp")}>
          {formatDistanceToNow(new Date(value), { addSuffix: true })}
        </span>
      ),
    },
    {
      key: "event_type" as keyof TimelineEvent,
      label: "Event",
      width: 140,
      render: (value: string) => (
        <Badge variant="outline" className={getEventTypeClassName(value)}>
          {value}
        </Badge>
      ),
    },
    {
      key: "category" as keyof TimelineEvent,
      label: "Category",
      width: 120,
      render: (value: string | null | undefined) =>
        value ? (
          <Badge variant="outline" className="capitalize">
            {value.replace(/_/g, " ")}
          </Badge>
        ) : (
          <span className="text-onSurface-default-tertiary">--</span>
        ),
    },
    {
      key: "source_agent" as keyof TimelineEvent,
      label: "Agent",
      width: 100,
    },
    {
      key: "summary" as keyof TimelineEvent,
      label: "Summary",
      width: "auto" as const,
      render: (value: string | null | undefined) => (
        <span className="text-onSurface-default-primary">{value || "--"}</span>
      ),
    },
    {
      key: "memory_ids" as keyof TimelineEvent,
      label: "Memories",
      width: 100,
      render: (value: string[] | undefined) =>
        value && value.length > 0 ? (
          <Badge variant="outline">→ {value.length}</Badge>
        ) : (
          <span className="text-onSurface-default-tertiary">--</span>
        ),
    },
    {
      key: "id" as keyof TimelineEvent,
      label: "Scope",
      width: 240,
      render: (_: string, row: TimelineEvent) => (
        <span className="font-mono text-xs text-onSurface-default-secondary truncate">
          {scopeLabel(row)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold font-fustat">Timeline</h1>
          <p className="text-sm text-onSurface-default-secondary">
            Narrative history of memory activity across agents and projects.
          </p>
          {lastUpdated && (
            <p className="text-xs text-onSurface-default-tertiary">
              Last updated{" "}
              {formatDistanceToNow(new Date(lastUpdated), { addSuffix: true })}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Select value={selectedProject} onValueChange={setSelectedProject}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="All projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_PROJECTS}>All projects</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project} value={project}>
                  {project}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => void refetch()} disabled={isLoading}>
            <RefreshCw className="size-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton rows={6} columns={7} />
      ) : events.length === 0 ? (
        <EmptyState
          image="requests"
          title="No timeline events yet"
          description={
            selectedProject === ALL_PROJECTS
              ? "Events appear once agents start sessions or store memories with timeline logging enabled."
              : `No events recorded for project "${selectedProject}".`
          }
        />
      ) : (
        <Card className="border-memBorder-primary overflow-hidden">
          <DataTable
            data={events}
            columns={columns}
            getRowKey={(row) => row.id}
          />
        </Card>
      )}
    </div>
  );
}
