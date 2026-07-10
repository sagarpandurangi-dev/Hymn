import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import HeaderAvatar from "@/src/components/HeaderAvatar";

type Journey = {
  id: string;
  title: string;
  description: string;
  target_completion_date: string;
  status: string;
  created_at: string;
  updated_at: string;
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary,
  archived: colors.onSurfaceTertiary,
};

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

export default function LearnScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const items = await api.listLearningJourneys();
      setJourneys(items);
    } catch (e: any) {
      setError(e?.message || "Could not load learning journeys");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="learn-screen">
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.title}>Learn</Text>
          <Text style={styles.subtitle}>Learning journeys</Text>
        </View>
        <View style={styles.headerActions}>
          <Pressable
            onPress={() => router.push("/learn/add")}
            testID="learn-add-button"
            hitSlop={12}
            style={styles.addBtn}
          >
            <Ionicons name="add" size={22} color={colors.onSurface} />
          </Pressable>
          <HeaderAvatar />
        </View>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} style={styles.retry} testID="learn-retry">
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : journeys.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="school-outline" size={44} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No journeys yet.</Text>
          <Text style={styles.emptyText}>What do you want to learn?</Text>
          <Pressable onPress={() => router.push("/learn/add")} style={styles.emptyCta} testID="learn-empty-add-button">
            <Text style={styles.emptyCtaText}>Start a journey</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        >
          {journeys.map((j) => (
            <Pressable
              key={j.id}
              onPress={() => router.push(`/learn/${j.id}`)}
              style={styles.card}
              testID={`learn-row-${j.id}`}
            >
              <View style={styles.cardTop}>
                <Text style={styles.tag}>LEARNING</Text>
                <View style={styles.statusPill}>
                  <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[j.status] || colors.brandPrimary }]} />
                  <Text style={styles.statusText}>{j.status}</Text>
                </View>
              </View>
              <Text style={styles.cardTitle} numberOfLines={2}>{j.title}</Text>
              {j.description ? <Text style={styles.cardDesc} numberOfLines={2}>{j.description}</Text> : null}
              {j.target_completion_date ? (
                <View style={styles.metaRow}>
                  <Ionicons name="calendar-outline" size={13} color={colors.onSurfaceTertiary} />
                  <Text style={styles.meta}>by {formatDate(j.target_completion_date)}</Text>
                </View>
              ) : null}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  headerLeft: { flex: 1 },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  subtitle: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  addBtn: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
  },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl * 2, gap: spacing.md },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  retryText: { color: colors.onSurface },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600", textAlign: "center" },
  emptyText: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  tag: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  cardTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600", lineHeight: 24 },
  cardDesc: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.xs, lineHeight: 18 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.sm },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary },
});
