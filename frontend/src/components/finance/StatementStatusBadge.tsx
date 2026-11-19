import { FoldPill } from "@/src/components/finance/foldUi";
import { dateLabel } from "@/src/lib/finance/format";
import type { Statement } from "@/src/lib/api";

/** "start – end" for a statement's metadata period, or "" when unknown. */
export const periodLabel = (m?: Statement["metadata"]) => {
  if (!m?.period_start && !m?.period_end) return "";
  return `${m?.period_start ? dateLabel(m.period_start) : "?"} – ${m?.period_end ? dateLabel(m.period_end) : "?"}`;
};

const STATUS: Record<string, { label: string; tone: "neutral" | "warn" | "err" | "ok" | "info" }> = {
  reading: { label: "Reading…", tone: "info" },
  ready: { label: "✓ Adds up", tone: "ok" },
  needs_review: { label: "Needs review", tone: "warn" },
  failed: { label: "Couldn't read", tone: "err" },
};

export default function StatementStatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <FoldPill label={s.label} tone={s.tone} />;
}
