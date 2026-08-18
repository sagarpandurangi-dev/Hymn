/**
 * Behavioural Calibration screen — reads /api/finance/calibration and
 * lets the user see how their override pattern is shaping the assessor.
 *
 * Sections:
 *   1. Hero — total overrides, trend arrow, vindicated/regretted split.
 *   2. Softening summary — which buckets now soften future assessments.
 *   3. By priority · By domain · By currency — sorted lists with mini
 *      progress bars showing the vindicated-ratio.
 *   4. How it works — explainer footer.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api, type CalibrationProfile, type CalibrationBucket } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

// ---------------------------------------------------------------------------
// Presentational helpers
// ---------------------------------------------------------------------------
const AXIS_TITLES: Record<string, string> = {
  by_priority: "By priority",
  by_domain: "By domain",
  by_currency: "By currency",
};

function prettyValue(v: string): string {
  if (!v || v === "unknown") return "Unknown";
  return v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------
export default function CalibrationScreen() {
  const router = useRouter();
  const [profile, setProfile] = useState<CalibrationProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setProfile(await api.getCalibration()); }
    catch (e: any) { setError(e?.message || "Could not load calibration"); }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Ionicons.Button
          name="chevron-back"
          size={22}
          color={colors.onSurface}
          backgroundColor="transparent"
          onPress={() => router.back()}
          iconStyle={{ marginRight: 0 }}
          style={styles.backBtn}
          testID="calibration-back"
        />
        <Text style={styles.headerTitle}>Calibration</Text>
        <View style={{ width: 22 }} />
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: spacing.xxxl }} color={colors.brandPrimary} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.onSurfaceSecondary} />}
        >
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {!profile || profile.total === 0 ? (
            <EmptyState />
          ) : (
            <>
              <Hero profile={profile} />
              <SofteningSummary profile={profile} />
              <AxisSection title={AXIS_TITLES.by_priority} rows={profile.by_priority} testIDPrefix="cal-priority" />
              <AxisSection title={AXIS_TITLES.by_domain} rows={profile.by_domain} testIDPrefix="cal-domain" />
              <AxisSection title={AXIS_TITLES.by_currency} rows={profile.by_currency} testIDPrefix="cal-currency" />
              <Explainer minCount={profile.soften_min_count} minRatio={profile.soften_min_ratio} />
            </>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function EmptyState() {
  return (
    <View style={styles.emptyWrap} testID="calibration-empty">
      <Ionicons name="pulse-outline" size={36} color={colors.onSurfaceTertiary} />
      <Text style={styles.emptyTitle}>Nothing to calibrate yet</Text>
      <Text style={styles.emptyBody}>
        When you proceed despite a warning on a new commitment, Hymn records the decision and its outcome.
        Once a few of those decisions have played out, this screen will show your pattern — and the assessor
        will start softening warnings that your history has proven harmless.
      </Text>
    </View>
  );
}

function Hero({ profile }: { profile: CalibrationProfile }) {
  const { vindicated, regretted, pending } = profile.outcomes;
  const resolved = vindicated + regretted;
  const ratio = resolved > 0 ? vindicated / resolved : null;
  const trendUp = profile.trend.last_90d > (profile.trend.last_180d - profile.trend.last_90d);

  return (
    <View style={styles.hero} testID="calibration-hero">
      <Text style={styles.eyebrow}>OVERRIDES</Text>
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: spacing.md }}>
        <Text style={styles.heroNumber}>{profile.total}</Text>
        <Text style={styles.heroCaption}>total</Text>
        <View style={{ flex: 1 }} />
        <View style={styles.trendChip}>
          <Ionicons name={trendUp ? "trending-up" : "trending-down"} size={14} color={colors.onSurfaceSecondary} />
          <Text style={styles.trendText}>{profile.trend.last_90d} in 90d</Text>
        </View>
      </View>
      <View style={styles.heroDivider} />
      <View style={styles.statRow}>
        <Stat label="Vindicated" value={vindicated} tone="ok" />
        <Stat label="Regretted" value={regretted} tone="err" />
        <Stat label="Pending" value={pending} tone="muted" />
      </View>
      {ratio != null ? (
        <Text style={styles.heroFoot}>
          {(ratio * 100).toFixed(0)}% of resolved overrides ended up vindicated.
        </Text>
      ) : null}
    </View>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "ok" | "err" | "muted" }) {
  const color = tone === "ok" ? "#4A6F52" : tone === "err" ? "#B36B57" : colors.onSurfaceTertiary;
  return (
    <View style={styles.statCell}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label.toUpperCase()}</Text>
    </View>
  );
}

function SofteningSummary({ profile }: { profile: CalibrationProfile }) {
  const softenBuckets = [
    ...profile.by_priority.filter((r) => r.softens).map((r) => ({ axis: "priority", ...r })),
    ...profile.by_domain.filter((r) => r.softens).map((r) => ({ axis: "domain", ...r })),
    ...profile.by_currency.filter((r) => r.softens).map((r) => ({ axis: "currency", ...r })),
  ];
  if (softenBuckets.length === 0) {
    return (
      <View style={styles.softCard} testID="calibration-nosoften">
        <View style={styles.softHead}>
          <Ionicons name="options-outline" size={16} color={colors.onSurfaceSecondary} />
          <Text style={styles.softTitle}>No warnings softened yet</Text>
        </View>
        <Text style={styles.softBody}>
          A bucket needs at least {profile.soften_min_count} overrides with a{" "}
          ≥ {(profile.soften_min_ratio * 100).toFixed(0)}% vindicated ratio before Hymn will
          start softening similar warnings.
        </Text>
      </View>
    );
  }
  return (
    <View style={styles.softCard} testID="calibration-softening">
      <View style={styles.softHead}>
        <Ionicons name="options-outline" size={16} color="#4A6F52" />
        <Text style={styles.softTitle}>{softenBuckets.length} bucket{softenBuckets.length === 1 ? "" : "s"} now softening</Text>
      </View>
      <View style={{ gap: 6 }}>
        {softenBuckets.map((b, i) => (
          <Text key={`${b.axis}-${b.value}-${i}`} style={styles.softLine}>
            • {prettyValue(b.axis)} = {prettyValue(b.value)} · {b.vindicated}/{b.count} vindicated
          </Text>
        ))}
      </View>
    </View>
  );
}

function AxisSection({ title, rows, testIDPrefix }: { title: string; rows: CalibrationBucket[]; testIDPrefix: string }) {
  if (!rows || rows.length === 0) return null;
  return (
    <View style={styles.axisSection} testID={`${testIDPrefix}-section`}>
      <Text style={styles.axisTitle}>{title.toUpperCase()}</Text>
      <View style={styles.axisCard}>
        {rows.map((r, idx) => (
          <View
            key={r.value}
            style={[styles.axisRow, idx > 0 && styles.axisDivider]}
            testID={`${testIDPrefix}-row-${r.value}`}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.axisLabel}>{prettyValue(r.value)}</Text>
                {r.softens ? (
                  <View style={styles.softPill}>
                    <Text style={styles.softPillText}>SOFTENING</Text>
                  </View>
                ) : null}
              </View>
              <Text style={styles.axisMeta}>
                {r.count} override{r.count === 1 ? "" : "s"} · {r.vindicated} vindicated · {r.regretted} regretted
              </Text>
              {r.vindicated_ratio != null ? (
                <View style={styles.progressTrack}>
                  <View style={[styles.progressFill, { width: `${Math.round(r.vindicated_ratio * 100)}%` }]} />
                </View>
              ) : null}
            </View>
            <Text style={styles.axisPct}>
              {r.vindicated_ratio != null ? `${Math.round(r.vindicated_ratio * 100)}%` : "—"}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function Explainer({ minCount, minRatio }: { minCount: number; minRatio: number }) {
  return (
    <View style={styles.explainer}>
      <Text style={styles.explainerTitle}>How this works</Text>
      <Text style={styles.explainerBody}>
        Every override is auto-tagged when its commitment completes: <Text style={styles.strong}>vindicated</Text> if
        the actual outflow stayed inside the reserved envelope, <Text style={styles.strong}>regretted</Text> if it
        overran or the commitment was cancelled. When a bucket accumulates at least {minCount} overrides with a
        vindicated ratio ≥ {(minRatio * 100).toFixed(0)}%, the assessor softens its classification by one level on
        future proposals in that bucket (severe → warning, or warning → safe). It never escalates.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
  },
  backBtn: { padding: 0 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.lg },
  error: { color: colors.error, fontSize: 13 },

  emptyWrap: { alignItems: "center", padding: spacing.xxxl, gap: spacing.md },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  emptyBody: { fontSize: 13.5, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 20 },

  hero: {
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.lg, borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
    gap: spacing.sm,
  },
  eyebrow: { fontSize: 10.5, letterSpacing: 1.6, color: colors.onSurfaceSecondary, fontWeight: "700" },
  heroNumber: { fontFamily: fonts.displayBold, fontSize: 44, letterSpacing: -1, color: colors.onSurface },
  heroCaption: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.3 },
  heroDivider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginVertical: spacing.sm },
  trendChip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: colors.surface, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  trendText: { fontSize: 11, color: colors.onSurfaceSecondary, fontWeight: "600" },
  statRow: { flexDirection: "row", gap: spacing.md },
  statCell: { flex: 1 },
  statValue: { fontFamily: fonts.displayBold, fontSize: 22, fontWeight: "700" },
  statLabel: { fontSize: 10, letterSpacing: 1.2, color: colors.onSurfaceSecondary, marginTop: 2, fontWeight: "700" },
  heroFoot: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic", marginTop: 4 },

  softCard: { padding: spacing.md, borderRadius: radius.md, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, gap: spacing.xs },
  softHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  softTitle: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  softBody: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 },
  softLine: { fontSize: 12, color: colors.onSurface },

  axisSection: { gap: spacing.sm },
  axisTitle: { fontSize: 11, letterSpacing: 1.4, color: colors.onSurfaceSecondary, fontWeight: "700" },
  axisCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, overflow: "hidden" },
  axisRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md },
  axisDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  axisLabel: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  axisMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  axisPct: { fontSize: 15, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  progressTrack: { marginTop: 6, height: 4, borderRadius: 999, backgroundColor: colors.border },
  progressFill: { height: 4, borderRadius: 999, backgroundColor: "#4A6F52" },
  softPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, backgroundColor: "#E6EDE3" },
  softPillText: { fontSize: 9, letterSpacing: 0.8, color: "#4A6F52", fontWeight: "700" },

  explainer: { padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, gap: 4 },
  explainerTitle: { fontSize: 12, letterSpacing: 1.4, color: colors.onSurfaceSecondary, fontWeight: "700" },
  explainerBody: { fontSize: 12.5, color: colors.onSurfaceSecondary, lineHeight: 19 },
  strong: { color: colors.onSurface, fontWeight: "700" },
});
