# Timeline UI enhancements — design

## Problem

The Timeline page (`server/dashboard/src/app/(root)/dashboard/timeline/page.tsx`)
truncates every event's summary to two lines (`line-clamp-2`) with no way to
see the rest, and the `→ N memories` badge on `add_memory`/merge events is
inert — it shows a count but isn't clickable, so there's no way to see what
memory it actually links to. Separately, the shared `DataTable` component
(`server/dashboard/src/components/shared/data-table.tsx`) renders any
null/undefined cell value as the literal string `"null"`/`"undefined"` (its
default cell renderer is `String(value)`), which shows up on the Memories
page's Agent column for every memory with no `agent_id`.

## Scope

Three changes, no backend work required — `payload` and `memory_ids` are
already returned by `GET /timeline/events`, and `GET /memories/{id}` already
exists for fetching a linked memory's detail.

1. Expandable timeline rows.
2. A popup for viewing memory(s) linked to a timeline event.
3. Fix `DataTable`'s default cell rendering so null/undefined/empty values
   show a placeholder instead of the literal string "null"/"undefined".

## 1. Expandable rows

`TimelinePage` gets one new piece of state: `expandedEventId: string | null`.
Clicking anywhere on a row (outside the memory-link badge, which stops
propagation) toggles it. When a row's id matches `expandedEventId`:

- The `line-clamp-2` on the summary paragraph is dropped, showing full text.
- If `event.payload` is non-empty, render its entries as a small
  label/value block beneath the summary (e.g. `Query: "dashboard fix"`,
  `Results: 3`, or `Command: git push origin ...`) — this data has been
  populated server-side since today's daemon.py change but nothing
  currently displays it.
- A chevron (`ChevronDown`/`ChevronRight` from lucide-react, already the
  icon library in use) sits at the row's right edge, rotating on expand,
  matching the existing hover-row treatment.

Only one row expands at a time (single id in state, not a Set) — this is a
narrow activity feed meant to be scanned quickly, not a document viewer.

## 2. Memory-link popup

The `→ N memories` badge becomes a `<button>` (keeps existing badge
styling) that opens a `Dialog` (shadcn primitive already in
`components/ui/dialog.tsx`).

New component: `MemoryLinkDialog` (colocated at
`timeline/memory-link-dialog.tsx`, not shared elsewhere yet), props
`{ memoryIds: string[]; open: boolean; onOpenChange: (open: boolean) => void }`.

- **1 memory_id**: fetches `GET /memories/{id}` (lazily, only while the
  dialog is open, via `useApiQuery`'s `enabled` flag) and renders the full
  `memory` text plus `metadata.category`/`metadata.importance`/
  `metadata.project` directly — no intermediate list view.
- **&gt;1 memory_id**: fires one `GET /memories/{id}` per id in parallel
  (counts here are small — a Dream cluster merge, not bulk data) and shows
  a compact list first (id prefix, `line-clamp-1` text, category badge).
  Clicking a list row switches the dialog to that memory's detail view,
  with a back arrow returning to the list.
- Loading state: skeleton rows/text while fetching.
- If a fetch 404s (memory deleted since the event was logged), show "Memory
  no longer exists" in place of that entry rather than failing the whole
  dialog.

State added to `TimelinePage`: `memoryDialogEvent: TimelineEvent | null` —
non-null drives both the dialog's open state and which event's
`memory_ids` to pass in.

## 3. DataTable null rendering

`data-table.tsx`'s default cell branch:

```tsx
column.render
  ? column.render(value, row)
  : String(value)
```

becomes:

```tsx
column.render
  ? column.render(value, row)
  : value === null || value === undefined || value === ""
    ? <span className="text-onSurface-default-tertiary">—</span>
    : String(value)
```

Fixes the Memories page's Agent column (and any other nullable column using
the default renderer) app-wide, not just agent_id specifically.

## Testing

No frontend test suite exists for dashboard pages currently (checked — none
present). Verification is manual: run the dashboard dev server and click
through — a row with payload data, a row without, a single-memory badge, a
multi-memory badge, and a memory that's been deleted (to confirm the
graceful-404 path). Confirm the Agent column shows "—" instead of "null"
for memories with no agent.
