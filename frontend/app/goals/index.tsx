import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Goal = {
  id: string; title: string; domain_id: string; domain_name: string;
  target_outcome: string; deadline: string; status: string; notes: string;
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary,
  paused: colors.warning,
  completed: colors.success,
  abandoned: colors.onSurfaceTertiary,
};

export default function GoalsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const items = await api.listGoals();
      setGoals(items);
    } catch (e: any) {
      setError(e?.message || "Could not load");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="goals-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="goals-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Goals</Text>
        <Pressable onPress={() => router.push("/goals/add")} testID="goals-add-button" hitSlop={12}>
          <Ionicons name="add" size={24} color={colors.onSurface} />
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} style={styles.retry}><Text>Retry</Text></Pressable>
        </View>
      ) : goals.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="flag-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No goals yet.</Text>
          <Text style={styles.emptyText}>What are you working towards?</Text>
          <Pressable onPress={() => router.push("/goals/add")} style={styles.emptyCta} testID="goals-empty-add-button">
            <Text style={styles.emptyCtaText}>Add goal</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        >
          {goals.map((g) => (
            <Pressable
              key={g.id}
              onPress={() => router.push(`/goals/${g.id}`)}
              style={styles.card}
              testID={`goal-row-${g.id}`}
            >
              <View style={styles.cardTop}>
                <Text style={styles.domain}>{(g.domain_name || "—").toUpperCase()}</Text>
                <View style={styles.statusPill}>
                  <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[g.status] || colors.brandPrimary }]} />
                  <Text style={styles.statusText}>{g.status}</Text>
                </View>
              </View>
              <Text style={styles.title} numberOfLines={2}>{g.title}</Text>
              {g.deadline ? <Text style={styles.meta}>by {g.deadline}</Text> : null}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 20, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600", textAlign: "center" },
  emptyText: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  domain: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  title: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600", lineHeight: 24 },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
});
