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

type Entry = {
  id: string;
  title: string;
  time: string;
  amount: string;
  notes: string;
  goal_id: string | null;
  task_id: string | null;
  expected_outcome_id: string | null;
};

type Group = {
  currency: string;
  total: string;
  entries: Entry[];
};

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const localTodayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const formatMoney = (v: string): string => {
  if (!v) return "0";
  const [i, f] = v.split(".");
  const withCommas = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return f ? `${withCommas}.${f}` : withCommas;
};

const formatHeader = () => {
  const d = new Date();
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
};

export default function SpendingScreen() {
  const router = useRouter();
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.getSpending(localTodayISO());
      setGroups(res.groups);
    } catch {
      setGroups([]);
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

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const isEmpty = groups.length === 0;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="spending-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Today&apos;s Spending</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        testID="spending-screen"
      >
        <Text style={styles.dateHead}>{formatHeader()}</Text>

        {loading ? (
          <View style={styles.center} testID="spending-loading">
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        ) : isEmpty ? (
          <View style={styles.emptyWrap} testID="spending-empty">
            <Ionicons name="cash-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>No spending logged today.</Text>
            <Text style={styles.emptyBody}>
              Add money spent while creating a check-in and it will show up here.
            </Text>
          </View>
        ) : (
          groups.map((g) => (
            <View key={g.currency} style={styles.card} testID={`spending-group-${g.currency}`}>
              <View style={styles.cardHead}>
                <Text style={styles.currency}>{g.currency}</Text>
                <Text style={styles.total}>{formatMoney(g.total)}</Text>
              </View>
              <View style={styles.entries}>
                {g.entries.map((e) => (
                  <View key={e.id} style={styles.entry} testID={`spending-entry-${e.id}`}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.entryTitle} numberOfLines={1}>{e.title}</Text>
                      <Text style={styles.entryMeta}>{e.time || "—"}{e.notes ? ` · ${e.notes}` : ""}</Text>
                    </View>
                    <Text style={styles.entryAmount}>{formatMoney(e.amount)}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))
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
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  dateHead: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  center: { paddingVertical: spacing.xxxl, alignItems: "center" },
  emptyWrap: { alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingVertical: spacing.xxxl },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm },
  emptyBody: { fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center", paddingHorizontal: spacing.xl },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  currency: { fontSize: 14, color: colors.onSurfaceSecondary, letterSpacing: 1, fontWeight: "700" },
  total: { fontSize: 20, color: colors.onSurface, fontWeight: "700" },
  entries: { gap: spacing.xs },
  entry: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
  },
  entryTitle: { fontSize: 14, color: colors.onSurface },
  entryMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  entryAmount: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
});
