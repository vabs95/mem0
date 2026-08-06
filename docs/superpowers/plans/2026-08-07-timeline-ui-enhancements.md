# Timeline UI Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Timeline dashboard page's rows expandable (full summary text + structured payload detail) and its "→ N memories" badge clickable, opening a popup with the linked memory/memories' full content.

**Architecture:** Two additions to the existing client-rendered `TimelinePage` (`server/dashboard/src/app/(root)/dashboard/timeline/page.tsx`), which already fetches `TimelineEvent[]` (including `payload` and `memory_ids`, both already returned by the API — no backend changes needed). A new colocated `MemoryLinkDialog` component fetches linked memories on demand via the existing `GET /memories/{id}` endpoint.

**Tech Stack:** Next.js (App Router) + React, TypeScript, Tailwind, shadcn/radix `Dialog`, `axios` via the existing `api` client, `useApiQuery`/manual `useEffect` for data fetching, `lucide-react` icons.

## Global Constraints

- No backend/API changes — `payload` and `memory_ids` are already in the `TimelineEvent` API response; `GET /memories/{id}` already exists.
- No new dependencies — use only what's already imported elsewhere in this dashboard (`@radix-ui/react-dialog` via `components/ui/dialog.tsx`, `axios`, `lucide-react`).
- No frontend test suite exists for dashboard pages (verified: none present) — verification is `npm run typecheck`, `npm run lint`, and a manual click-through in the running dev server, not new unit tests.
- Match existing Tailwind design tokens already used in this file (`text-onSurface-default-secondary`, `text-onSurface-default-tertiary`, `border-memBorder-primary`, `bg-surface-default-secondary`, etc.) — don't introduce new ad hoc colors.
- Note: the DataTable null-rendering fix (agent showing "null") from the same spec is **already implemented and committed** (`server/dashboard/src/components/shared/data-table.tsx`, commit `45f356a8`) — not part of this plan's tasks.

---

### Task 1: Build the `MemoryLinkDialog` component

**Files:**
- Create: `server/dashboard/src/app/(root)/dashboard/timeline/memory-link-dialog.tsx`

**Interfaces:**
- Consumes: `Memory`, `MemoryMetadata` from `@/types/api`; `MEMORY_ENDPOINTS.BY_ID(id: string): string` from `@/utils/api-endpoints`; `api` (axios instance) from `@/utils/api`; `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle` from `@/components/ui/dialog`; `Badge` from `@/components/ui/badge`; `Skeleton` from `@/components/ui/skeleton`.
- Produces: `MemoryLinkDialog` component with props `{ memoryIds: string[]; open: boolean; onOpenChange: (open: boolean) => void }`. Consumed by Task 2.

- [ ] **Step 1: Write the component**

```tsx
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
          <Badge variant="outline" className="px-1.5 py-0 text-[10px] capitalize">
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

export function MemoryLinkDialog({ memoryIds, open, onOpenChange }: MemoryLinkDialogProps) {
  const [results, setResults] = useState<
    Record<string, { status: FetchStatus; memory?: Memory }>
  >(() => Object.fromEntries(memoryIds.map((id) => [id, { status: "loading" as FetchStatus }])));
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
          setResults((prev) => ({ ...prev, [id]: { status: "success", memory: res.data } }));
        })
        .catch((err) => {
          if (cancelled) return;
          const status: FetchStatus =
            axios.isAxiosError(err) && err.response?.status === 404 ? "notfound" : "error";
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
              <p className="text-sm text-destructive">Failed to load this memory.</p>
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
                    <p className="text-xs text-destructive">Failed to load ({id.slice(0, 8)})</p>
                  ) : (
                    <div className="space-y-1">
                      <p className="text-xs text-onSurface-default-primary line-clamp-1">
                        {entry.memory!.memory}
                      </p>
                      {entry.memory!.metadata?.category && (
                        <Badge variant="outline" className="px-1.5 py-0 text-[10px] capitalize">
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
```

- [ ] **Step 2: Typecheck and lint**

Run (from `server/dashboard/`): `npm run typecheck && npm run lint`
Expected: both pass with no errors referencing `memory-link-dialog.tsx`.

- [ ] **Step 3: Commit**

```bash
git add server/dashboard/src/app/\(root\)/dashboard/timeline/memory-link-dialog.tsx
git commit -m "feat(dashboard): add MemoryLinkDialog for viewing timeline-linked memories"
```

---

### Task 2: Wire expandable rows + payload detail + memory-link dialog into `TimelinePage`

**Files:**
- Modify: `server/dashboard/src/app/(root)/dashboard/timeline/page.tsx`

**Interfaces:**
- Consumes: `MemoryLinkDialog` from `./memory-link-dialog` (Task 1); existing `TimelineEvent` type (already has `payload?: Record<string, unknown> | null` and `memory_ids: string[]`).
- Produces: nothing consumed elsewhere — this is the page itself.

- [ ] **Step 1: Add the `ChevronDown` icon import**

In the existing `lucide-react` import block (top of file), add `ChevronDown` to the list:

```tsx
import {
  Archive,
  BrainCircuit,
  ChevronDown,
  Circle,
  LogIn,
  LogOut,
  MessageSquare,
  RefreshCw,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
```

- [ ] **Step 2: Import `MemoryLinkDialog`**

Add near the other local component imports (after the `DateRangePicker` import):

```tsx
import { MemoryLinkDialog } from "./memory-link-dialog";
```

- [ ] **Step 3: Add a payload-formatting helper**

Add this near the other module-level helpers (`scopeLabel`, `dayLabel`), before `export default function TimelinePage()`:

```tsx
const PAYLOAD_LABELS: Record<string, string> = {
  query: "Query",
  result_count: "Results",
  command: "Command",
};

const formatPayloadEntries = (
  payload: Record<string, unknown> | null | undefined,
): [string, string][] => {
  if (!payload) return [];
  return Object.entries(payload)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [PAYLOAD_LABELS[key] ?? key.replace(/_/g, " "), String(value)]);
};
```

- [ ] **Step 4: Add expand and memory-dialog state**

Inside `TimelinePage`, alongside the existing `useState` declarations (after `const [search, setSearch] = useState("");`):

```tsx
const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
const [memoryDialogEvent, setMemoryDialogEvent] = useState<TimelineEvent | null>(null);
```

- [ ] **Step 5: Replace the row-rendering block**

Find this block (the `.map` over `filteredEvents` inside the `<Card>`):

```tsx
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
```

Replace it with:

```tsx
            {filteredEvents.map((event, index) => {
              const meta = eventMeta(event.event_type);
              const Icon = meta.icon;
              const showDaySeparator =
                index === 0 ||
                !isSameDay(new Date(event.created_at), new Date(filteredEvents[index - 1].created_at));
              const scope = scopeLabel(event);
              const isExpanded = expandedEventId === event.id;
              const payloadEntries = formatPayloadEntries(event.payload);

              return (
                <div key={event.id}>
                  {showDaySeparator && (
                    <div className="px-4 py-1.5 bg-surface-default-secondary/60 text-xs font-medium text-onSurface-default-tertiary sticky top-0">
                      {dayLabel(event.created_at)}
                    </div>
                  )}
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setExpandedEventId((prev) => (prev === event.id ? null : event.id))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setExpandedEventId((prev) => (prev === event.id ? null : event.id));
                      }
                    }}
                    className="flex items-start gap-3 px-4 py-3 hover:bg-surface-default-secondary/40 transition-colors cursor-pointer"
                  >
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
                      <p
                        className={cn(
                          "text-sm text-onSurface-default-primary",
                          !isExpanded && "line-clamp-2",
                        )}
                      >
                        {event.summary || (
                          <span className="text-onSurface-default-tertiary italic">
                            {event.event_type.replace(/_/g, " ")}
                          </span>
                        )}
                      </p>
                      {isExpanded && payloadEntries.length > 0 && (
                        <div className="mt-2 space-y-1 rounded-md border border-memBorder-primary bg-surface-default-secondary/40 p-2 text-xs">
                          {payloadEntries.map(([label, value]) => (
                            <div key={label} className="flex gap-2">
                              <span className="font-medium text-onSurface-default-secondary shrink-0">
                                {label}:
                              </span>
                              <span className="text-onSurface-default-tertiary break-all">{value}</span>
                            </div>
                          ))}
                        </div>
                      )}
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
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setMemoryDialogEvent(event);
                            }}
                            className="inline-flex"
                          >
                            <Badge
                              variant="outline"
                              className="px-1.5 py-0 text-[10px] hover:bg-surface-default-secondary cursor-pointer"
                            >
                              → {event.memory_ids.length} memor{event.memory_ids.length === 1 ? "y" : "ies"}
                            </Badge>
                          </button>
                        )}
                        {scope && <span className="font-mono truncate">{scope}</span>}
                      </div>
                    </div>
                    <ChevronDown
                      className={cn(
                        "size-4 shrink-0 mt-1 text-onSurface-default-tertiary transition-transform",
                        isExpanded && "rotate-180",
                      )}
                    />
                  </div>
                </div>
              );
            })}
```

- [ ] **Step 6: Render the dialog**

Find the closing of the events `<Card>` block:

```tsx
        </Card>
      )}
    </div>
  );
}
```

Replace with (adds the dialog render right after the conditional block, still inside the outer `<div className="space-y-4">`):

```tsx
        </Card>
      )}

      {memoryDialogEvent && (
        <MemoryLinkDialog
          key={memoryDialogEvent.id}
          memoryIds={memoryDialogEvent.memory_ids}
          open
          onOpenChange={(open) => {
            if (!open) setMemoryDialogEvent(null);
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 7: Typecheck and lint**

Run (from `server/dashboard/`): `npm run typecheck && npm run lint`
Expected: both pass with no errors.

- [ ] **Step 8: Commit**

```bash
git add server/dashboard/src/app/\(root\)/dashboard/timeline/page.tsx
git commit -m "feat(dashboard): expandable timeline rows with payload detail and memory-link dialog"
```

---

### Task 3: Manual verification

**Files:** none (verification only).

- [ ] **Step 1: Start the dashboard dev server**

From `server/dashboard/`: `npm run dev` (or use the `run` skill if driving a browser). Confirm it's pointed at a backend with real timeline data (the self-hosted VPS instance, or local data if running against a local API).

- [ ] **Step 2: Verify row expansion**

Open the Timeline page. Click a row whose summary is long enough to have been clamped. Confirm: full text shows, chevron rotates, clicking again collapses it back to 2 lines.

- [ ] **Step 3: Verify payload detail**

Find (or trigger, e.g. via a `search_memories` MCP call) a `post_tool_use` row for a memory search. Expand it. Confirm the "Query"/"Results" (or "Command" for a Bash row) block renders under the summary.

- [ ] **Step 4: Verify single-memory dialog**

Click a `→ 1 memory` badge. Confirm: row does NOT also toggle expand/collapse (click didn't propagate), dialog opens directly to that memory's detail (no intermediate list), shows full text + category/importance/project badges as applicable, closes via the X or clicking outside.

- [ ] **Step 5: Verify multi-memory dialog**

Find or trigger an event linking more than one memory (e.g. a Dream merge, if any exist). Click its badge. Confirm: list view shows first, clicking an entry shows that memory's detail, "Back to list" returns to the list.

- [ ] **Step 6: Verify deleted-memory edge case**

Pick a memory id from a timeline event, delete that memory via the Memories page, then reopen that event's dialog on Timeline. Confirm it shows "Memory no longer exists" instead of erroring the whole dialog.

- [ ] **Step 7: Verify the Agent column fix (already shipped, confirm it's live)**

Open the Memories page. Confirm memories with no agent show "—" in the Agent column, not the literal text "null".
