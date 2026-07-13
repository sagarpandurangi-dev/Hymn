import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type RequiredCheckin = {
  goal_id: string;
  goal_title: string;
  domain_name: string;
  checkin_cadence: string;
  completed_for_period: boolean;
};

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const localTodayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const cadenceLabel = (c: string) => (c ? c.charAt(0).toUpperCase() + c.slice(1) : "");

export default function CheckInsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<RequiredCheckin[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.listRequiredCheckins(localTodayISO());
      setItems(res as RequiredCheckin[]);
    } catch {
      setItems([]);
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
      return () => {
        alive = false;
      };
    }, [load]),
  );

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="check-ins-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Required Check-ins</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />
        }
        testID="check-ins-screen"
      >
        {loading ? (
          <View style={styles.center} testID="check-ins-loading">
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        ) : items.length === 0 ? (
          <View style={styles.center} testID="check-ins-empty">
            <Ionicons name="checkmark-circle-outline" size={44} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>All caught up</Text>
            <Text style={styles.emptyBody}>No check-ins scheduled.</Text>
          </View>
        ) : (
          <View style={styles.list}>
            {items.map((r) => (
              <Pressable
                key={r.goal_id}
                style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
                onPress={() =>
                  router.push(`/checkin/goal?goalId=${encodeURIComponent(r.goal_id)}`)
                }
                testID={`check-in-item-${r.goal_id}`}
              >
                <View style={styles.cardBody}>
                  <Text style={styles.goalTitle} numberOfLines={2}>{r.goal_title}</Text>
                  <View style={styles.metaRow}>
                    <Text style={styles.metaDomain}>{r.domain_name || "—"}</Text>
                    <Text style={styles.metaDot}>·</Text>
                    <Text style={styles.metaCadence}>{cadenceLabel(r.checkin_cadence)}</Text>
                  </View>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
              </Pressable>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
  },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.xxxl,
    flexGrow: 1,
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.xxxl,
    gap: spacing.sm,
  },
  emptyTitle: { fontSize: 16, color: colors.onSurface, fontWeight: "600", marginTop: spacing.sm },
  emptyBody: { fontSize: 13, color: colors.onSurfaceSecondary },
  list: { gap: spacing.md },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  cardBody: { flex: 1, gap: spacing.xs },
  goalTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  metaDomain: { fontSize: 12, color: colors.onSurfaceSecondary },
  metaDot: { fontSize: 12, color: colors.onSurfaceTertiary },
  metaCadence: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
});
