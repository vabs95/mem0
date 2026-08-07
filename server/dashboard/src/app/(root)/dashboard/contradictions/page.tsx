import { redirect } from "next/navigation";

// Contradictions/Supersede moved onto the combined Dream page (see
// dashboard/dream/page.tsx's Supersede tab) -- this route stays only so
// old links/bookmarks land somewhere real instead of a 404.
export default function ContradictionsPage() {
  redirect("/dashboard/dream?tab=supersede");
}
