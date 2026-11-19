/** Shared bits for "Habits to change". Supportive tone, no streaks. */
import { formatINR } from "@/src/lib/finance/format";

export const TRIGGERS = [
  { code: "stress", label: "Stress" },
  { code: "after_meal", label: "After a meal" },
  { code: "with_friends", label: "With friends" },
  { code: "bored", label: "Bored" },
  { code: "tired", label: "Tired" },
];
export const triggerLabel = (c: string) => TRIGGERS.find((t) => t.code === c)?.label ?? c.replace(/_/g, " ");

export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const reasonOf = (h: any) => h?.serves?.title ?? h?.for_what ?? "";

/** "3 of the last 5 days on track" — never a streak. */
export const progressLine = (p: any) =>
  p && Number(p.days_logged) > 0 ? (Number(p.days_logged) === 1 ? `${p.days_on_track} of 1 day on track` : `${p.days_on_track} of the last ${p.days_logged} days on track`) : "No days logged yet";

export const freedLine = (p: any) => {
  const bits: string[] = [];
  if (p?.money_freed != null && Number(p.money_freed) > 0) bits.push(`${formatINR(p.money_freed)} freed`);
  if (p?.hours_freed != null && Number(p.hours_freed) > 0) bits.push(`${Number(p.hours_freed).toLocaleString("en-IN", { maximumFractionDigits: 1 })} hours freed`);
  return bits.join(" · ");
};

/** top_triggers comes as [["stress", 3], …] or [{trigger, count}]. */
export const topTriggers = (list: any[] = []) =>
  list.map((t) => (Array.isArray(t) ? { code: String(t[0]), count: Number(t[1]) } : { code: String(t.trigger ?? t.code ?? t), count: Number(t.count ?? 0) }));
