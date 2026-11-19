import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { niceDate, VerdictBadge } from "@/src/components/planner/PlanCard";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export const plansOf = (res: any): any[] => (Array.isArray(res) ? res : res?.items ?? res?.plans ?? []);

export default function MyPlansScreen() {
  const router = useRouter();
  const [plans, setPlans] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setPlans(plansOf(await api.listLifePlans()));
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your plans.");
      setPlans([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="my-plans-screen">
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/planner" as any))} hitSlop={12} style={styles.iconBtn} testID="my-plans-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>My plans</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {plans === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : plans.length === 0 ? (
          <View style={styles.empty} testID="my-plans-empty">
            <Text style={styles.emptyText}>No active plans yet. Talk it through in the planner and pick one with “Go with this”.</Text>
            <Pressable style={styles.btn} onPress={() => router.replace("/planner" as any)} testID="my-plans-open-planner">
              <Text style={styles.btnText}>Open the planner</Text>
            </Pressable>
          </View>
        ) : plans.map((p) => (
          <Pressable key={p.id} style={({ pressed }) => [styles.row, pressed && { opacity: 0.85 }]} onPress={() => router.push(`/planner/${p.id}` as any)} testID={`my-plan-${p.id}`}>
            <View style={{ flex: 1, gap: 6 }}>
              <Text style={styles.name}>{p.title}</Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
                <VerdictBadge verdict={p.verdict} />
                {p.target_date ? <Text style={styles.sub}>By {niceDate(p.target_date)}</Text> : null}
              </View>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 24, fontWeight: "700", color: colors.onSurface },
  scroll: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxxl },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 72, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  name: { fontSize: 16, fontWeight: "600", color: colors.onSurface },
  sub: { fontSize: 13, color: colors.onSurfaceSecondary },
  empty: { gap: spacing.md, paddingVertical: spacing.xl },
  emptyText: { fontSize: 14, lineHeight: 20, color: colors.onSurfaceSecondary },
  btn: { minHeight: 48, borderRadius: radius.pill, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  btnText: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 15 },
  error: { fontSize: 13, color: colors.error },
});
