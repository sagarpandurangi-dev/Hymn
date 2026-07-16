/**
 * Finance-specific formatting helpers. These are DISPLAY ONLY. No math
 * happens here — every derived value comes from the backend.
 */

export const formatMoney = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined) return "0";
  const s = typeof value === "number" ? String(value) : value;
  const [intPart, fracPart] = s.split(".");
  const withThousands = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fracPart ? `${withThousands}.${fracPart}` : withThousands;
};

export const formatSignedMoney = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined) return "0";
  const s = typeof value === "number" ? String(value) : value;
  return s.startsWith("-") ? formatMoney(s) : formatMoney(s);
};

/** Human-readable month label (e.g. "Jul 2026") from YYYY-MM. */
export const monthLabel = (m: string): string => {
  if (!m || m.length !== 7) return m;
  const [y, mo] = m.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const idx = Math.max(0, Math.min(11, parseInt(mo, 10) - 1));
  return `${names[idx]} ${y}`;
};

/** Human-readable date label (e.g. "30 Sep 2026") from YYYY-MM-DD. */
export const dateLabel = (d: string): string => {
  if (!d || d.length !== 10) return d;
  const [y, m, dd] = d.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const idx = Math.max(0, Math.min(11, parseInt(m, 10) - 1));
  return `${parseInt(dd, 10)} ${names[idx]} ${y}`;
};

export const priorityColor = (p: string): string => {
  switch (p) {
    case "critical": return "#c62828";
    case "high": return "#e57c00";
    case "medium": return "#6a6a6a";
    default: return "#8a8a8a";
  }
};

export const stateLabel = (s: string): string => {
  switch (s) {
    case "draft": return "Draft";
    case "reserved": return "Reserved";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
    default: return s;
  }
};

export const stateColor = (s: string): string => {
  switch (s) {
    case "draft": return "#8a8a8a";
    case "reserved": return "#1c73c1";
    case "completed": return "#2e7d32";
    case "cancelled": return "#8a8a8a";
    case "expired": return "#c62828";
    default: return "#6a6a6a";
  }
};

export const todayIso = (): string => {
  const d = new Date();
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

export const currentMonthIso = (): string => {
  const d = new Date();
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};
