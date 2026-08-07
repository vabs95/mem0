"use client";

import { useState } from "react";
import { CalendarIcon, Check } from "lucide-react";
import { format } from "date-fns";
import { DateRange } from "react-day-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface DateRangePreset {
  label: string;
  days: number | null;
}

export type DateRangeSelection =
  | { mode: "preset"; key: string }
  | { mode: "custom"; from: Date; to: Date };

interface DateRangePickerProps {
  presets: Record<string, DateRangePreset>;
  value: DateRangeSelection;
  onChange: (value: DateRangeSelection) => void;
  className?: string;
}

export function DateRangePicker({ presets, value, onChange, className }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [showCalendar, setShowCalendar] = useState(false);
  const [draftRange, setDraftRange] = useState<DateRange | undefined>(
    value.mode === "custom" ? { from: value.from, to: value.to } : undefined,
  );

  const label =
    value.mode === "preset"
      ? (presets[value.key]?.label ?? "All time")
      : `${format(value.from, "MMM d, yyyy")} - ${format(value.to, "MMM d, yyyy")}`;

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) setShowCalendar(false);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" className={cn("w-[200px] justify-start gap-2 font-normal", className)}>
          <CalendarIcon className="size-4 shrink-0" />
          <span className="truncate">{label}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        {!showCalendar ? (
          <div className="w-[200px] py-1">
            {Object.entries(presets).map(([key, preset]) => (
              <button
                key={key}
                onClick={() => {
                  onChange({ mode: "preset", key });
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between px-3 py-1.5 text-sm text-left hover:bg-surface-default-secondary rounded-md"
              >
                {preset.label}
                {value.mode === "preset" && value.key === key && <Check className="size-3.5" />}
              </button>
            ))}
            <div className="h-px bg-memBorder-primary my-1" />
            <button
              onClick={() => setShowCalendar(true)}
              className="flex w-full items-center px-3 py-1.5 text-sm text-left hover:bg-surface-default-secondary rounded-md"
            >
              Custom range...
            </button>
          </div>
        ) : (
          <div>
            <Calendar
              mode="range"
              selected={draftRange}
              onSelect={setDraftRange}
              numberOfMonths={2}
              defaultMonth={draftRange?.from}
            />
            <div className="flex items-center justify-end gap-2 p-3 border-t border-memBorder-primary">
              <Button variant="outline" size="sm" onClick={() => setShowCalendar(false)}>
                Back
              </Button>
              <Button
                size="sm"
                disabled={!draftRange?.from || !draftRange?.to}
                onClick={() => {
                  if (!draftRange?.from || !draftRange?.to) return;
                  onChange({ mode: "custom", from: draftRange.from, to: draftRange.to });
                  setOpen(false);
                  setShowCalendar(false);
                }}
              >
                Apply
              </Button>
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
