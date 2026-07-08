import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Task = { id: string; title: string; status: string; priority: string; due_date: string; origin: string };

const STATUS_COLORS: Record<string, string> = {
  todo: colors.brandPrimary,
  done: colors.success,
  deferred: colors.warning,
};

export default function TasksScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);

  const load = useCallback(async () => {
    try {
      const items = await api.listTasks();
      setTasks(items);
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const quickUpdate = async (id: string, patch: any) => {
    await api.updateTask(id, patch);
    await load();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="tasks-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="tasks-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Tasks</Text>
        <Pressable onPress={() => router.push("/tasks/add")} testID="tasks-add-button" hitSlop={12}>
          <Ionicons name="add" size={24} color={colors.onSurface} />
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : tasks.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="list-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No tasks yet.</Text>
          <Pressable onPress={() => router.push("/tasks/add")} style={styles.emptyCta} testID="tasks-empty-add-button">
            <Text style={styles.emptyCtaText}>Add task</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
          {tasks.map((t) => (
            <Pressable key={t.id} onPress={() => router.push(`/tasks/${t.id}`)} style={styles.card} testID={`task-row-${t.id}`}>
              <View style={{ flex: 1 }}>
                <View style={styles.top}>
                  <View style={styles.pill}>
                    <View style={[styles.dot, { backgroundColor: STATUS_COLORS[t.status] || colors.brandPrimary }]} />
                    <Text style={styles.pillText}>{t.status}</Text>
                  </View>
                  <Text style={styles.priority}>{t.priority.toUpperCase()}</Text>
                </View>
                <Text style={styles.title} numberOfLines={2}>{t.title}</Text>
                {t.due_date ? <Text style={styles.meta}>due {t.due_date}</Text> : null}
              </View>
              {t.status !== "done" && (
                <Pressable
                  hitSlop={8}
                  onPress={(e) => { e.stopPropagation(); quickUpdate(t.id, { status: "done" }); }}
                  testID={`task-done-${t.id}`}
                >
                  <Ionicons name="checkmark-circle-outline" size={26} color={colors.success} />
                </Pressable>
              )}
              {t.status === "todo" && (
                <Pressable
                  hitSlop={8}
                  onPress={(e) => { e.stopPropagation(); quickUpdate(t.id, { status: "deferred" }); }}
                  testID={`task-defer-${t.id}`}
                >
                  <Ionicons name="time-outline" size={22} color={colors.warning} />
                </Pressable>
              )}
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
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.sm },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  priority: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1 },
  title: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
});
