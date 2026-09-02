// Correction 2: canonical helper for constructing a device-local,
// timezone-aware ISO 8601 timestamp from a check-in's date + time. The
// backend refuses naive strings (no silent +00:00 append) so the
// frontend is the source of the offset.
//
// Never treat a user's local date/time as UTC.

function pad(n: number, w = 2) { return String(n).padStart(w, "0"); }

/**
 * Build a tz-aware ISO 8601 string like "2026-06-15T18:34:00+05:30"
 * from a YYYY-MM-DD date and an HH:MM time. Uses the device's current
 * timezone offset. Returns null if the inputs cannot be parsed.
 */
export function toLocalTimezoneIso(dateYmd: string, timeHm: string | null | undefined): string | null {
  if (!dateYmd) return null;
  const [y, mo, d] = dateYmd.split("-").map((v) => parseInt(v, 10));
  if (!y || !mo || !d) return null;
  let h = 12, m = 0;
  if (timeHm && /^\d{1,2}:\d{2}$/.test(timeHm)) {
    const [hs, ms] = timeHm.split(":").map((v) => parseInt(v, 10));
    h = isFinite(hs) ? hs : 12;
    m = isFinite(ms) ? ms : 0;
  }
  const local = new Date(y, mo - 1, d, h, m, 0);
  if (isNaN(local.getTime())) return null;
  const off = -local.getTimezoneOffset(); // minutes east of UTC
  const sign = off >= 0 ? "+" : "-";
  const oh = pad(Math.floor(Math.abs(off) / 60));
  const om = pad(Math.abs(off) % 60);
  return (
    `${pad(y, 4)}-${pad(mo)}-${pad(d)}` +
    `T${pad(h)}:${pad(m)}:00` +
    `${sign}${oh}:${om}`
  );
}
