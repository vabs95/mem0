"use client";

import { useEffect, useMemo, useState } from "react";
import { format, formatDistanceToNow, isSameDay, subDays } from "date-fns";
import {
  Archive,
  BrainCircuit,
  Circle,
  LogIn,
  LogOut,
  MessageSquare,
  RefreshCw,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { cn } from "@/lib/utils";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, TIMELINE_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, TimelineEvent } from "@/types/api";

const EVENT_LIMIT = 150;
const ALL_PROJECTS = "__all__";
const ALL_CATEGORIES = "__all__";

const DATE_RANGES = {
  all: { label: "All time", days: null },
  "1": { label: "Last 24 hours", days: 1 },
  "7": { label: "Last 7 days", days: 7 },
  "30": { label: "Last 30 days", days: 30 },
} as const;
type DateRangeKey = keyof typeof DATE_RANGES;

const EVENT_TYPE_PILLS: { value: string; label: string }[] = [
  { value: "__all__", label: "All" },
  { value: "session_start", label: "Session" },
  { value: "user_prompt", label: "Prompt" },
  { value: "add_memory", label: "Memory" },
  { value: "post_tool_use", label: "Tool use" },
  { value: "stop", label: "Stop" },
];

const EVENT_META: Record<string, { icon: typeof Circle; className: string }> = {
  session_start: {
    icon: LogIn,
    className: "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
  },
  user_prompt: {
    icon: MessageSquare,
    className:
      "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300",
  },
  add_memory: {
    icon: BrainCircuit,
    className:
      "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  },
  post_tool_use: {
    icon: Wrench,
    className:
      "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
  },
  stop: {
    icon: LogOut,
    className:
      "bg-surface-default-secondary text-onSurface-default-secondary",
  },
  delete_all: {
    icon: Trash2,
    className: "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  },
  pre_compact: {
    icon: Archive,
    className:
      "bg-surface-default-secondary text-onSurface-default-secondary",
  },
};

const eventMeta = (eventType: string) =>
  EVENT_META[eventType] ?? {
    icon: Circle,
    className: "bg-surface-default-secondary text-onSurface-default-secondary",
  };

const scopeLabel = (event: TimelineEvent): string => {
  const parts: string[] = [];
  if (event.user_id) parts.push(event.user_id);
  if (event.agent_id) parts.push(event.agent_id);
  if (event.project) parts.push(event.project);
  if (event.run_id) parts.push(event.run_id);
  return parts.join(" · ");
};

const dayLabel = (dateStr: string): string => {
  const date = new Date(dateStr);
  const today = new Date();
  if (isSameDay(date, today)) return "Today";
  if (isSameDay(date, subDays(today, 1))) return "Yesterday";
  return format(date, "EEEE, MMM d");
};

export default function TimelinePage() {
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<string>(ALL_PROJECTS);
  const [selectedCategory, setSelectedCategory] = useState<string>(ALL_CATEGORIES);
  const [selectedEventType, setSelectedEventType] = useState<string>("__all__");
  const [dateRange, setDateRange] = useState<DateRangeKey>("all");
  const [search, setSearch] = useState("");

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
      const range = DATE_RANGES[dateRange];
      const res = await api.get<TimelineEvent[]>(TIMELINE_ENDPOINTS.EVENTS, {
        params: {
          limit: EVENT_LIMIT,
          project: selectedProject === ALL_PROJECTS ? undefined : selectedProject,
          category: selectedCategory === ALL_CATEGORIES ? undefined : selectedCategory,
          event_type: selectedEventType === "__all__" ? undefined : selectedEventType,
          since: range.days ? subDays(new Date(), range.days).toISOString() : undefined,
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
  }, [selectedProject, selectedCategory, selectedEventType, dateRange]);

  const categoryOptions = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => e.category && set.add(e.category));
    return Array.from(set).sort();
  }, [events]);

  const filteredEvents = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return events;
    return events.filter((e) => {
      const haystack = [e.summary, e.source_agent, e.user_id, e.agent_id, e.project, e.run_id]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [events, search]);

  const hasActiveFilters =
    selectedProject !== ALL_PROJECTS ||
    selectedCategory !== ALL_CATEGORIES ||
    selectedEventType !== "__all__" ||
    dateRange !== "all" ||
    search.trim() !== "";

  const clearFilters = () => {
    setSelectedProject(ALL_PROJECTS);
    setSelectedCategory(ALL_CATEGORIES);
    setSelectedEventType("__all__");
    setDateRange("all");
    setSearch("");
  };

  return (
    <div className="space-y-4">
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
        <Button variant="outline" onClick={() => void refetch()} disabled={isLoading}>
          <RefreshCw className="size-4 mr-2" />
          Refresh
        </Button>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-onSurface-default-tertiary" />
            <Input
              placeholder="Search summaries, agents, scope..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <Select value={selectedProject} onValueChange={setSelectedProject}>
            <SelectTrigger className="w-[160px]">
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
          <Select value={selectedCategory} onValueChange={setSelectedCategory}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_CATEGORIES}>All categories</SelectItem>
              {categoryOptions.map((category) => (
                <SelectItem key={category} value={category}>
                  {category.replace(/_/g, " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {EVENT_TYPE_PILLS.map((pill) => (
            <button
              key={pill.value}
              onClick={() => setSelectedEventType(pill.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                selectedEventType === pill.value
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
        <Card className="border-memBorder-primary p-4 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-start gap-3 animate-pulse">
              <div className="size-8 rounded-full bg-surface-default-secondary shrink-0" />
              <div className="flex-1 space-y-2 py-1">
                <div className="h-3.5 w-2/3 rounded bg-surface-default-secondary" />
                <div className="h-3 w-1/3 rounded bg-surface-default-secondary" />
              </div>
            </div>
          ))}
        </Card>
      ) : filteredEvents.length === 0 ? (
        <EmptyState
          image="requests"
          title="No timeline events"
          description={
            hasActiveFilters
              ? "No events match the current filters."
              : "Events appear once agents start sessions or store memories with timeline logging enabled."
          }
        >
          {hasActiveFilters && (
            <Button variant="outline" size="sm" className="mt-3" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </EmptyState>
      ) : (
        <Card className="border-memBorder-primary overflow-hidden">
          <div className="divide-y divide-memBorder-primary">
            {filteredEvents.map((event, index) => {
              const meta = eventMeta(event.event_type);
              const Icon = meta.icon;
              const showDaySeparator =
                index === 0 ||
                !isSameDay(new Date(event.created_at), new Date(filteredEvents[index - 1].created_at));
              const scope = scopeLabel(event);

              return (
                <div key={event.id}>
                  {showDaySeparator && (
                    <div className="px-4 py-1.5 bg-surface-default-secondary/60 text-xs font-medium text-onSurface-default-tertiary sticky top-0">
                      {dayLabel(event.created_at)}
                    </div>
                  )}
                  <div className="flex items-start gap-3 px-4 py-3 hover:bg-surface-default-secondary/40 transition-colors">
                    <div
                      className={cn(
                        "flex size-8 shrink-0 items-center justify-center rounded-full",
                        meta.className,
                      )}
                      title={event.event_type}
                    >
                      <Icon className="size-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-onSurface-default-primary line-clamp-2">
                        {event.summary || (
                          <span className="text-onSurface-default-tertiary italic">
                            {event.event_type.replace(/_/g, " ")}
                          </span>
                        )}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-onSurface-default-tertiary">
                        <span title={format(new Date(event.created_at), "PPpp")}>
                          {formatDistanceToNow(new Date(event.created_at), { addSuffix: true })}
                        </span>
                        <span>·</span>
                        <Badge variant="outline" className="px-1.5 py-0 text-[10px] capitalize">
                          {event.source_agent}
                        </Badge>
                        {event.category && (
                          <Badge variant="outline" className="px-1.5 py-0 text-[10px] capitalize">
                            {event.category.replace(/_/g, " ")}
                          </Badge>
                        )}
                        {event.memory_ids.length > 0 && (
                          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                            → {event.memory_ids.length} memor{event.memory_ids.length === 1 ? "y" : "ies"}
                          </Badge>
                        )}
                        {scope && <span className="font-mono truncate">{scope}</span>}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
