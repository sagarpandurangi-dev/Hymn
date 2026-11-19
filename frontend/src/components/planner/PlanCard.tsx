/**
 * Life plan card: title, target date, verdict, "What must go right" and
 * "What may stop it". Booking / answering call the server and hand back the
 * refreshed plan via onChanged.
 */
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { formatINR } from "@/src/lib/finance/format";
import { colors, radius, spacing } from "@/src/lib/theme";

export const VERDICTS: Record<string, { label: string; bg: string; fg: string }> = {
  fits_now: { label: "Fits now", bg: colors.brandTertiary, fg: colors.success },
  fits_by_then: { label: "Fits by then", bg: colors.brandTertiary, fg: colors.success },
  needs_answers: { label: "Needs your answers", bg: colors.surfaceTertiary, fg: colors.warning },
  doesnt_fit: { label: "Doesn't fit yet", bg: colors.surfaceTertiary, fg: colors.error },
};

export function VerdictBadge({ verdict }: { verdict?: string }) {
  const v = verdict ? VERDICTS[verdict] : undefined;
  if (!v) return null;
  return (
    <View style={[styles.badge, { backgroundColor: v.bg }]} testID={`plan-verdict-${verdict}`}>
      <Text style={[styles.badgeText, { color: v.fg }]}>{v.label}</Text>
    </View>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const niceDate = (iso?: string | null) => {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : String(iso);
};

const money = (v: any, cur?: string) => {
  if (v == null || v === "") return "—";
  return !cur || cur === "INR" ? formatINR(v) : `${cur} ${v}`;
};
const num = (v: any) => (v == null ? "—" : Number.isFinite(Number(v)) ? Number(v).toLocaleString("en-IN") : String(v));
const mins = (v: any) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  const h = Math.floor(n / 60), m = n % 60;
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
};

function StatusTick({ status }: { status?: string }) {
  if (status === "now") return <View style={styles.tick}><Ionicons name="checkmark-circle" size={18} color={colors.success} /></View>;
  if (status === "by_then") return <View style={styles.tick}><Ionicons name="checkmark-circle-outline" size={18} color={colors.success} /><Text style={styles.tickText}>by then</Text></View>;
  if (status === "short") return <View style={styles.tick}><Ionicons name="close-circle" size={18} color={colors.error} /></View>;
  return <View style={styles.tick}><Ionicons name="help-circle-outline" size={18} color={colors.onSurfaceTertiary} /></View>;
}

function Facts({ items }: { items: [string, string][] }) {
  return (
    <View style={styles.facts}>
      {items.map(([k, v]) => (
        <View key={k} style={styles.fact}>
          <Text style={styles.factK}>{k}</Text>
          <Text style={styles.factV}>{v}</Text>
        </View>
      ))}
    </View>
  );
}

function Requirement({ plan, r, onChanged }: { plan: any; r: any; onChanged: (p: any) => void }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const act = async (tag: string, fn: () => Promise<any>) => {
    setBusy(tag);
    setError("");
    try {
      const res = await fn();
      onChanged(res?.id && res?.requirements ? res : await api.getLifePlan(plan.id));
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy("");
    }
  };

  let body: React.ReactNode = null;
  if (r.kind === "money") {
    body = <Facts items={[["Needed", money(r.amount, r.currency)], ["Available now", money(r.available_now, r.currency)], ["By then", money(r.built_up_by_then, r.currency)], ["Short", Number(r.gap) > 0 ? money(r.gap, r.currency) : "—"]]} />;
  } else if (r.kind === "time") {
    const slots: any[] = r.slots ?? [];
    body = (
      <View style={{ gap: spacing.sm }}>
        <Text style={styles.sub}>
          {[r.amount != null ? `Needs ${mins(r.amount)}` : "", r.min_block ? `in blocks of ${mins(r.min_block)}` : "", r.weekdays?.length ? `on ${r.weekdays.join(", ")}` : "", r.needed_by ? `by ${niceDate(r.needed_by)}` : ""].filter(Boolean).join(" ")}
        </Text>
        {slots.length === 0 ? <Text style={styles.sub}>No free slots found yet.</Text> : slots.map((s, i) => {
          const tag = `book-${i}`;
          const minutes = Number(s.minutes ?? r.min_block ?? r.amount ?? 60);
          return (
            <View key={i} style={styles.slot} testID={`plan-slot-${r.id}-${i}`}>
              <Text style={styles.slotText}>{niceDate(s.date)} · {s.start}{s.end ? `–${s.end}` : ""} · {mins(minutes)}</Text>
              {s.booked ? <Text style={styles.sub}>Booked</Text> : (
                <Pressable style={styles.smallBtn} disabled={!!busy} onPress={() => act(tag, () => api.bookLifePlanSlot(plan.id, { requirement_id: r.id, date: s.date, start: s.start, minutes }))} testID={`plan-book-${r.id}-${i}`}>
                  {busy === tag ? <ActivityIndicator size="small" color={colors.onBrandPrimary} /> : <Text style={styles.smallBtnText}>Book</Text>}
                </Pressable>
              )}
            </View>
          );
        })}
      </View>
    );
  } else if (r.kind === "condition") {
    const opts: { code: "yes" | "no" | "unknown"; label: string }[] = [{ code: "yes", label: "Yes" }, { code: "no", label: "No" }, { code: "unknown", label: "Not yet" }];
    body = (
      <View style={styles.answerRow}>
        {opts.map((o) => {
          const on = r.answer === o.code;
          return (
            <Pressable key={o.code} style={[styles.answer, on && styles.answerOn]} disabled={!!busy} onPress={() => act(o.code, () => api.answerLifePlanRequirement(plan.id, r.id, o.code))} testID={`plan-answer-${o.code}-${r.id}`}>
              {busy === o.code ? <ActivityIndicator size="small" color={colors.onSurface} /> : <Text style={[styles.answerText, on && styles.answerTextOn]}>{o.label}</Text>}
            </Pressable>
          );
        })}
      </View>
    );
  } else if (r.kind === "health") {
    const unit = r.unit ? ` ${r.unit}` : "";
    body = (
      <View style={{ gap: 2 }}>
        <Text style={styles.factV}>Now {num(r.available_now)} · Aim {num(r.target)}{unit}</Text>
        {r.building ? <Text style={[styles.sub, { color: colors.success }]}>Building up</Text> : null}
        {r.note ? <Text style={styles.sub}>{r.note}</Text> : null}
      </View>
    );
  }

  return (
    <View style={styles.req} testID={`plan-req-${r.id}`}>
      <View style={styles.reqHead}>
        <View style={{ flex: 1 }}>
          <Text style={styles.area}>{String(r.area ?? r.kind ?? "").toUpperCase()}</Text>
          <Text style={styles.what}>{r.what}</Text>
        </View>
        <StatusTick status={r.status} />
      </View>
      {body}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

export default function PlanCard({ plan, onChanged, footer }: { plan: any; onChanged: (p: any) => void; footer?: React.ReactNode }) {
  const reqs: any[] = plan?.requirements ?? [];
  const risks: any[] = plan?.risks ?? [];
  return (
    <View style={styles.card} testID={`plan-card-${plan.id}`}>
      <Text style={styles.title}>{plan.title}</Text>
      <View style={styles.metaRow}>
        {plan.target_date ? <Text style={styles.sub}>By {niceDate(plan.target_date)}</Text> : null}
        <VerdictBadge verdict={plan.verdict} />
        {plan.status && plan.status !== "draft" ? <Text style={styles.sub}>· {plan.status}</Text> : null}
      </View>

      <Text style={styles.section}>What must go right</Text>
      {reqs.length === 0 ? <Text style={styles.sub}>Nothing listed yet.</Text> : reqs.map((r) => <Requirement key={r.id} plan={plan} r={r} onChanged={onChanged} />)}

      {risks.length > 0 ? (
        <>
          <Text style={styles.section}>What may stop it</Text>
          {risks.map((k, i) => (
            <View key={k.id ?? i} style={styles.req} testID={`plan-risk-${i}`}>
              <View style={styles.reqHead}>
                <Text style={[styles.what, { flex: 1 }]}>{k.what}</Text>
                {k.likelihood ? <Text style={[styles.likely, k.likelihood === "high" && { color: colors.error }]}>{k.likelihood}</Text> : null}
              </View>
              {k.early_warning ? <Text style={styles.sub}><Text style={styles.label}>Early warning: </Text>{k.early_warning}</Text> : null}
              {k.mitigation ? <Text style={styles.sub}><Text style={styles.label}>What to do: </Text>{k.mitigation}</Text> : null}
            </View>
          ))}
        </>
      ) : null}
      {footer}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  title: { fontSize: 18, fontWeight: "700", color: colors.onSurface },
  metaRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.sm },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  badgeText: { fontSize: 12, fontWeight: "700" },
  section: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: spacing.md, letterSpacing: 0.4 },
  req: { backgroundColor: colors.surface, borderRadius: radius.sm, padding: spacing.md, gap: spacing.sm },
  reqHead: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  area: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceTertiary, letterSpacing: 0.6 },
  what: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
  tick: { flexDirection: "row", alignItems: "center", gap: 4 },
  tickText: { fontSize: 12, color: colors.success },
  facts: { flexDirection: "row", flexWrap: "wrap", rowGap: spacing.sm },
  fact: { width: "50%" },
  factK: { fontSize: 12, color: colors.onSurfaceTertiary },
  factV: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  sub: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  label: { fontWeight: "700", color: colors.onSurfaceSecondary },
  likely: { fontSize: 12, fontWeight: "700", color: colors.warning, textTransform: "capitalize" },
  slot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  slotText: { flex: 1, fontSize: 14, color: colors.onSurface },
  smallBtn: { minHeight: 36, minWidth: 64, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  smallBtnText: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 13 },
  answerRow: { flexDirection: "row", gap: spacing.sm },
  answer: { flex: 1, minHeight: 40, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center" },
  answerOn: { backgroundColor: colors.onSurface, borderColor: colors.onSurface },
  answerText: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  answerTextOn: { color: colors.surface },
  error: { fontSize: 13, color: colors.error },
});
