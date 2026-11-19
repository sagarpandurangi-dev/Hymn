import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { api, ApiError, InboxPatternsResponse } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";

const asText = (v: any): string =>
  typeof v === "string" ? v : v?.text ?? v?.title ?? v?.summary ?? JSON.stringify(v);

function BulletList({ title, items, testID }: { title: string; items?: any[]; testID: string }) {
  if (!items || items.length === 0) return null;
  return (
    <View style={styles.card} testID={testID}>
      <Text style={styles.cardTitle}>{title}</Text>
      {items.map((it, i) => (
        <Text key={i} style={styles.bullet}>• {asText(it)}</Text>
      ))}
    </View>
  );
}

export default function WeeklySummaryScreen() {
  const router = useRouter();
  const [data, setData] = useState<InboxPatternsResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pulling, setPulling] = useState(false);
  const [refreshingNow, setRefreshingNow] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await api.getInboxPatterns());
      setNotFound(false);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 404) {
        setNotFound(true);
        setData(null);
      } else {
        setError(err.message);
      }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        setLoading(true);
        await load();
        if (alive) setLoading(false);
      })();
      return () => { alive = false; };
    }, [load]),
  );

  const refreshNow = async () => {
    if (refreshingNow) return;
    setRefreshingNow(true);
    setError("");
    try {
      setData(await api.refreshInboxPatterns());
      setNotFound(false);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setRefreshingNow(false);
    }
  };

  const stats = data?.stats;
  const insight = data?.insight;
  const counts: { label: string; value?: number }[] = [
    { label: "Captured", value: stats?.captured },
    { label: "Completed", value: stats?.completed },
    { label: "Discarded", value: stats?.discarded },
    { label: "Migrated", value: stats?.migrated },
  ];

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="patterns-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Weekly summary</Text>
        <View style={{ width: 56 }} />
      </View>
      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={[s.scroll, { gap: spacing.md }]}
          refreshControl={<RefreshControl refreshing={pulling} onRefresh={async () => { setPulling(true); await load(); setPulling(false); }} tintColor={colors.brandPrimary} />}
        >
          {notFound ? (
            <Text style={styles.empty} testID="patterns-empty">Your first weekly summary arrives on your chosen day.</Text>
          ) : null}

          {data ? (
            <>
              {insight?.summary ? <Text style={styles.summary} testID="patterns-summary">{insight.summary}</Text> : null}
              {insight ? (
                <>
                  <BulletList title="Themes" items={insight.themes} testID="patterns-themes" />
                  <BulletList title="Avoidance" items={insight.avoidance} testID="patterns-avoidance" />
                  <BulletList title="Suggestions" items={insight.suggestions} testID="patterns-suggestions" />
                </>
              ) : null}

              <View style={styles.countRow} testID="patterns-counts">
                {counts.map((c) => (
                  <View key={c.label} style={styles.countBox}>
                    <Text style={styles.countValue}>{c.value ?? 0}</Text>
                    <Text style={styles.countLabel}>{c.label}</Text>
                  </View>
                ))}
              </View>

              {stats?.avoided && stats.avoided.length > 0 ? (
                <View style={styles.card} testID="patterns-avoided">
                  <Text style={styles.cardTitle}>Kept putting off</Text>
                  {stats.avoided.map((a, i) => (
                    <View key={a.id ?? i} style={styles.avoidedRow}>
                      <Text style={styles.avoidedText}>{a.text}</Text>
                      <Text style={styles.avoidedMeta}>reviewed {a.review_count}×</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </>
          ) : null}

          {error ? <Text style={s.errorText} testID="patterns-error">{error}</Text> : null}

          <Pressable
            style={[s.cta, { marginTop: spacing.md }, refreshingNow && s.ctaDisabled]}
            onPress={refreshNow}
            disabled={refreshingNow}
            testID="patterns-refresh-button"
          >
            {refreshingNow ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Refresh now</Text>}
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  empty: { fontSize: 14, color: colors.onSurfaceSecondary },
  summary: { fontSize: 16, lineHeight: 23, color: colors.onSurface },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.xs },
  cardTitle: { fontSize: 13, fontWeight: "600", color: colors.onSurface, marginBottom: spacing.xs },
  bullet: { fontSize: 14, color: colors.onSurface, lineHeight: 20 },
  countRow: { flexDirection: "row", gap: spacing.sm },
  countBox: { flex: 1, backgroundColor: colors.brandTertiary, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: "center" },
  countValue: { fontSize: 20, fontWeight: "700", color: colors.onBrandTertiary },
  countLabel: { fontSize: 11, color: colors.onBrandTertiary, marginTop: 2 },
  avoidedRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.xs },
  avoidedText: { flex: 1, fontSize: 14, color: colors.onSurface },
  avoidedMeta: { fontSize: 12, color: colors.onSurfaceSecondary },
});
