/** Family & Relationships helpers. Gentle wording: never "overdue", no streaks. */

export const PEOPLE_RELATIONS = [
  "mother", "father", "spouse", "partner", "child", "sibling", "grandparent", "grandchild",
  "parent_in_law", "relative", "friend", "mentor", "colleague", "neighbour", "other",
].map((code) => ({ code, label: code === "parent_in_law" ? "Parent-in-law" : code.charAt(0).toUpperCase() + code.slice(1) }));
export const relLabel = (c?: string) => PEOPLE_RELATIONS.find((r) => r.code === c)?.label ?? (c ?? "");

export const CIRCLES = [
  { code: "inner", label: "Inner circle" },
  { code: "close", label: "Close" },
  { code: "wider", label: "Wider" },
];

export const MOMENT_KINDS = [
  { code: "call", label: "Called", icon: "call-outline" },
  { code: "video_call", label: "Video call", icon: "videocam-outline" },
  { code: "visit", label: "Met", icon: "people-outline" },
  { code: "meal", label: "Meal", icon: "restaurant-outline" },
  { code: "message", label: "Messaged", icon: "chatbubble-outline" },
  { code: "help", label: "Helped", icon: "hand-left-outline" },
];
export const kindLabel = (c: string) =>
  MOMENT_KINDS.find((k) => k.code === c)?.label ?? ({ outing: "Outing", celebration: "Celebration", other: "Time together" } as Record<string, string>)[c] ?? c;

export const TIME_CHIPS = [
  { minutes: 15, label: "15m" },
  { minutes: 30, label: "30m" },
  { minutes: 60, label: "1h" },
  { minutes: 120, label: "2h+" },
];

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const parse = (iso: string) => { const [y, m, d] = iso.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };

/** "today", "tomorrow", "Friday" (within a week), else "21 Nov". */
export const whenText = (iso: string, inDays?: number) => {
  if (inDays === 0) return "today";
  if (inDays === 1) return "tomorrow";
  const d = parse(iso);
  if (inDays != null && inDays < 7) return WEEKDAYS[d.getDay()];
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
};

/** "Amma's birthday · Friday · turns 70". */
export const dayLine = (n: any, withName = true) => {
  if (!n) return "";
  const what = withName ? `${n.name}'s ${String(n.label).toLowerCase()}` : n.label;
  const turns = n.years && String(n.label).toLowerCase() === "birthday" ? ` · turns ${n.years}` : n.years ? ` · ${n.years} years` : "";
  return `${what} · ${whenText(n.on, n.in_days)}${turns}`;
};

/** "3 days ago" — soft phrasing. */
export const agoText = (days?: number | null) =>
  days == null ? "" : days === 0 ? "today" : days === 1 ? "yesterday" : days < 60 ? `${days} days ago` : `${Math.round(days / 30)} months ago`;

export const niceDate = (iso?: string) => (iso ? `${parse(iso).getDate()} ${MONTHS[parse(iso).getMonth()]}` : "");

export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
