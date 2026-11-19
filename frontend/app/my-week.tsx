import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

const p2 = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (s?: string) => {
  if (!s) return "";
  const [, m, d] = s.split("-");
  return `${parseInt(d, 10)} ${MONTHS[parseInt(m, 10) - 1]}`;
};
const addDays = (s: string, n: number) => {
  const [y, m, d] = s.split("-").map(Number);
  return iso(new Date(y, m - 1, d + n));
};
const h = (v: unknown) => {
  const n = Number(v ?? 0);
  return `${Number.isFinite(n) ? n.toFixed(1).replace(/\.0$/, "") : "0"}h`;
};
const signed = (v: unknown) => (Number(v) > 0 ? `+${h(v)}` : h(v));

// Falling short is bad for these; going over is bad for work and commute.
const SHORT_IS_BAD = ["learning", "health", "family"];
const OVER_IS_BAD = ["work", "commute"];
const gapBad = (area: string, gap: unknown) => {
  const g = Number(gap);
  return (SHORT_IS_BAD.includes(area) && g < 0) || (OVER_IS_BAD.includes(area) && g > 0);
};

function Section({ title, children, testID }: { title: string; children: React.ReactNode; testID: string }) {
  return (
    <View style={styles.section} testID={testID}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

/** Weekly time report: commitments, time spent per area, time flow. */
export default function MyWeekScreen() {
  const router = useRouter();
  const [weekStart, setWeekStart] = useState(iso(new Date()));
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const reqId = useRef(0);

  const load = useCallback(async (ws: string) => {
    const id = ++reqId.current;
    setError("");
    try {
      const res = await api.getTimeReport(ws);
      if (id === reqId.current) setData(res);
    } catch (e) {
      if (id === reqId.current) setError((e as ApiError).message);
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(weekStart); }, [load, weekStart]));

  const shift = (days: number) => {
    const base = data?.week_start ?? weekStart;
    setLoading(true);
    setOpen(null);
    setWeekStart(addDays(base, days));
  };

  const c = data?.commitments ?? {};
  const total = Number(data?.total_hours ?? c.total_hours ?? 168) || 168;
  const parts = [
    { key: "fixed", label: "Fixed", v: Number(c.fixed_hours ?? 0), color: colors.onSurface },
    { key: "flex", label: "Flexible & set aside", v: Number(c.flexible_and_set_aside_hours ?? 0), color: colors.brandPrimary },
    { key: "free", label: "Free", v: Number(c.free_hours ?? 0), color: colors.borderStrong },
  ];
  const spent = data?.spent ?? {};
  const areas: any[] = spent.areas ?? [];
  const flow = data?.flow ?? {};
  const assets: any[] = c.time_assets_this_year ?? [];

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} style={styles.iconBtn} testID="week-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>My week</Text>
        <View style={styles.iconBtn} />
      </View>
      <View style={styles.weekRow}>
        <Pressable onPress={() => shift(-7)} style={styles.iconBtn} testID="week-prev" accessibilityLabel="Previous week">
          <Ionicons name="chevron-back-circle-outline" size={28} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.weekText} testID="week-range">
          {data ? `${short(data.week_start)} – ${short(data.week_end)}` : "This week"}
        </Text>
        <Pressable onPress={() => shift(7)} style={styles.iconBtn} testID="week-next" accessibilityLabel="Next week">
          <Ionicons name="chevron-forward-circle-outline" size={28} color={colors.onSurface} />
        </Pressable>
      </View>

      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxl }} color={colors.brandPrimary} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(weekStart); setRefreshing(false); }} />}
        >
          {error ? <Text style={styles.error} testID="week-error">{error}</Text> : null}
          {data ? (
            <>
              {Number(data.untimed_checkins) > 0 ? (
                <View style={styles.notice} testID="week-untimed">
                  <Ionicons name="time-outline" size={16} color={colors.warning} />
                  <Text style={styles.noticeText}>
                    {data.untimed_checkins} check-in{Number(data.untimed_checkins) === 1 ? "" : "s"} this week {Number(data.untimed_checkins) === 1 ? "has" : "have"} no time
                  </Text>
                </View>
              ) : null}

              <Section title={`Commitments · out of ${h(total)}`} testID="week-commitments">
                <View style={styles.bar}>
                  {parts.map((p) => p.v > 0 ? <View key={p.key} style={{ flex: p.v / total, backgroundColor: p.color }} /> : null)}
                </View>
                {parts.map((p) => (
                  <View key={p.key} style={styles.row} testID={`week-commit-${p.key}`}>
                    <View style={[styles.dot, { backgroundColor: p.color }]} />
                    <Text style={styles.rowLabel}>{p.label}</Text>
                    <Text style={styles.rowVal}>{h(p.v)}</Text>
                  </View>
                ))}
                <Text style={styles.sub}>Time invested this year</Text>
                {assets.length === 0 ? <Text style={styles.muted}>Nothing yet.</Text> : assets.map((a, i) => (
                  <View key={i} style={styles.row} testID={`week-asset-${i}`}>
                    <Text style={styles.rowLabel}>{a.label ?? a.area}</Text>
                    <Text style={styles.rowVal}>{h(a.hours ?? a.hours_this_year ?? a.actual_hours)}</Text>
                  </View>
                ))}
              </Section>

              <Section title="Time spent" testID="week-spent">
                <View style={[styles.tRow, styles.tHead]}>
                  <Text style={[styles.tArea, styles.th]}>Area</Text>
                  <Text style={[styles.tNum, styles.th]}>Planned</Text>
                  <Text style={[styles.tNum, styles.th]}>Actual</Text>
                  <Text style={[styles.tNum, styles.th]}>Gap</Text>
                </View>
                {areas.length === 0 ? <Text style={styles.muted}>No planned or tracked time this week.</Text> : null}
                {areas.map((a) => {
                  const lines: any[] = a.lines ?? [];
                  const isOpen = open === a.area;
                  return (
                    <View key={a.area}>
                      <Pressable onPress={lines.length ? () => setOpen(isOpen ? null : a.area) : undefined} style={styles.tRow} testID={`week-area-${a.area}`}>
                        <View style={[styles.tArea, styles.areaCell]}>
                          {lines.length ? <Ionicons name={isOpen ? "chevron-down" : "chevron-forward"} size={12} color={colors.onSurfaceSecondary} /> : null}
                          <Text style={styles.areaText}>{a.label ?? a.area}</Text>
                        </View>
                        <Text style={styles.tNum}>{h(a.planned_hours)}</Text>
                        <Text style={styles.tNum}>{h(a.actual_hours)}</Text>
                        <Text style={[styles.tNum, gapBad(a.area, a.gap_hours) && styles.bad]} testID={`week-gap-${a.area}`}>{signed(a.gap_hours)}</Text>
                      </Pressable>
                      {isOpen ? lines.map((l, j) => (
                        <View key={j} style={[styles.tRow, styles.lineRow]} testID={`week-line-${a.area}-${j}`}>
                          <Text style={[styles.tArea, styles.lineText]} numberOfLines={2}>{l.label}</Text>
                          <Text style={[styles.tNum, styles.lineText]}>{l.planned_hours != null ? h(l.planned_hours) : ""}</Text>
                          <Text style={[styles.tNum, styles.lineText]}>{l.actual_hours != null ? h(l.actual_hours) : ""}</Text>
                          <Text style={[styles.tNum, styles.lineText]}>{l.gap_hours != null ? signed(l.gap_hours) : ""}</Text>
                        </View>
                      )) : null}
                    </View>
                  );
                })}
                {spent.show_soul ? (
                  <Text style={styles.soul} testID="week-soul">Soul (untracked): {h(spent.soul_hours)}</Text>
                ) : null}
                <Text style={styles.footnote} testID="week-waking">
                  Waking hours as planned: {Number(spent.waking_hours_as_planned_percent ?? 0)}%
                </Text>
              </Section>

              <Section title="Time flow" testID="week-flow">
                {[
                  ["Planned free", flow.planned_free_hours, "planned-free"],
                  ["Overruns", flow.overruns_hours, "overruns"],
                  ["Skipped plans", flow.skipped_plans_hours, "skipped"],
                  ["Untracked", flow.untracked_hours, "untracked"],
                ].map(([label, v, key], i) => (
                  <View key={String(key)} style={styles.flowRow} testID={`week-flow-${key}`}>
                    {i > 0 ? <Ionicons name="arrow-down" size={14} color={colors.onSurfaceTertiary} style={styles.flowArrow} /> : null}
                    <View style={styles.row}>
                      <Text style={styles.rowLabel}>{String(label)}</Text>
                      <Text style={styles.rowVal}>{h(v)}</Text>
                    </View>
                  </View>
                ))}
              </Section>
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.displayBold, fontSize: 22, fontWeight: "700", color: colors.onSurface },
  weekRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.md },
  weekText: { fontSize: 15, fontWeight: "600", color: colors.onSurface, minWidth: 140, textAlign: "center" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxxl * 2, gap: spacing.lg },
  section: { gap: spacing.sm },
  sectionTitle: { fontSize: 12, fontWeight: "700", letterSpacing: 0.6, color: colors.onSurfaceSecondary, textTransform: "uppercase" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  bar: { flexDirection: "row", height: 14, borderRadius: 7, overflow: "hidden", backgroundColor: colors.border, marginBottom: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 28, flex: 1 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  rowLabel: { flex: 1, fontSize: 14, color: colors.onSurface },
  rowVal: { fontSize: 14, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  sub: { fontSize: 13, fontWeight: "700", color: colors.onSurface, marginTop: spacing.sm },
  muted: { fontSize: 13, color: colors.onSurfaceSecondary },
  tRow: { flexDirection: "row", alignItems: "center", minHeight: 44, gap: spacing.xs },
  tHead: { minHeight: 24, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  th: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  tArea: { flex: 1 },
  areaCell: { flexDirection: "row", alignItems: "center", gap: 4 },
  areaText: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  tNum: { width: 62, textAlign: "right", fontSize: 14, color: colors.onSurface, fontVariant: ["tabular-nums"] },
  bad: { color: colors.error, fontWeight: "700" },
  lineRow: { minHeight: 32, paddingLeft: spacing.lg },
  lineText: { fontSize: 12, color: colors.onSurfaceSecondary },
  soul: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.sm, fontStyle: "italic" },
  footnote: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  flowRow: { gap: 2 },
  flowArrow: { alignSelf: "flex-start", marginLeft: 2 },
  notice: { flexDirection: "row", gap: spacing.sm, alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderLeftWidth: 3, borderLeftColor: colors.warning },
  noticeText: { flex: 1, fontSize: 14, color: colors.onSurface },
  error: { fontSize: 13, color: colors.error },
});
