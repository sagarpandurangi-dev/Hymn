import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import HeaderAvatar from "@/src/components/HeaderAvatar";

type EventItem = {
  id: string;
  type: string;
  title: string;
  date: string;
  time: string;
  notes: string;
};

type RequiredCheckin = {
  goal_id: string;
  goal_title: string;
  domain_name: string;
  checkin_cadence: string;
  completed_for_period: boolean;
};

type TaskItem = {
  id: string;
  title: string;
  due_date: string;
  priority: string;
  status: string;
};

// Generate YYYY-MM-DD from the local device date. Never use UTC — the user's
// wall-clock "today" is authoritative for scheduling comparisons.
const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const localTodayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const formatDateHeader = () => {
  const d = new Date();
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
};

const cadenceLabel = (c: string) => {
  if (!c) return "";
  return c.charAt(0).toUpperCase() + c.slice(1);
};

/** Compare two YYYY-MM-DD strings lexically. Empty strings sort last. */
const cmpDate = (a: string, b: string) => {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
};

function Card({
  testID,
  title,
  icon,
  empty,
  onPress,
  children,
}: {
  testID: string;
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  empty: string;
  onPress: () => void;
  children?: React.ReactNode;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
      onPress={onPress}
      testID={testID}
    >
      <View style={styles.cardHead}>
        <View style={styles.cardHeadLeft}>
          <Ionicons name={icon} size={18} color={colors.brandPrimary} />
          <Text style={styles.cardTitle}>{title}</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
      </View>
      {children ? children : <Text style={styles.cardEmpty}>{empty}</Text>}
    </Pressable>
  );
}

export default function TodayScreen() {
  const router = useRouter();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [required, setRequired] = useState<RequiredCheckin[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const today = localTodayISO();
    // Single Promise.all() feeds all three Today datasets in one refresh.
    // Any individual failure degrades that dataset only — the other two still
    // render — so returning to Today after completing a task or check-in
    // always reflects the newest state.
    const [checkinsRes, requiredRes, tasksRes] = await Promise.all([
      api.listCheckins().catch(() => []),
      api.listRequiredCheckins(today).catch(() => []),
      api.listTasks().catch(() => []),
    ]);

    // Recent Check-ins: only those recorded on the user's local "today".
    setEvents((checkinsRes as EventItem[]).filter((e) => e.date === today));

    setRequired(requiredRes as RequiredCheckin[]);

    // Upcoming tasks: exclude done + cancelled, then order Overdue -> Today
    // -> Future -> Undated. Undated tasks come last because they have no
    // temporal anchor.
    const bucket = (t: TaskItem): number => {
      if (!t.due_date) return 3;
      if (t.due_date < today) return 0;
      if (t.due_date === today) return 1;
      return 2;
    };
    const filtered = (tasksRes as TaskItem[]).filter(
      (t) => t.status !== "done" && t.status !== "cancelled",
    );
    filtered.sort((a, b) => {
      const ba = bucket(a);
      const bb = bucket(b);
      if (ba !== bb) return ba - bb;
      const dc = cmpDate(a.due_date || "", b.due_date || "");
      if (dc !== 0) return dc;
      return a.title.localeCompare(b.title);
    });
    setTasks(filtered);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const today = localTodayISO();
  const previewRequired = required.slice(0, 3);
  const moreRequired = Math.max(0, required.length - previewRequired.length);
  const previewTasks = tasks.slice(0, 3);
  const moreTasks = Math.max(0, tasks.length - previewTasks.length);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
      >
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.hello} testID="today-date-header">{formatDateHeader()}</Text>
            <Text style={styles.subhead}>Today.</Text>
          </View>
          <HeaderAvatar />
        </View>

        <View style={styles.stack}>
          <Card
            testID="card-check-ins"
            title="Required Check-ins"
            icon="checkmark-circle-outline"
            empty="No check-ins scheduled."
            onPress={() => router.push("/check-ins")}
          >
            {required.length > 0 ? (
              <View style={styles.rowList}>
                {previewRequired.map((r) => (
                  <Pressable
                    key={r.goal_id}
                    style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}
                    onPress={() => router.push(`/checkin/goal?goalId=${encodeURIComponent(r.goal_id)}`)}
                    testID={`required-checkin-row-${r.goal_id}`}
                  >
                    <Text style={styles.rowTitle} numberOfLines={1}>{r.goal_title}</Text>
                    <Text style={styles.rowMeta}>{cadenceLabel(r.checkin_cadence)}</Text>
                  </Pressable>
                ))}
                {moreRequired > 0 && (
                  <Text style={styles.moreLine} testID="required-checkin-more">+{moreRequired} more</Text>
                )}
              </View>
            ) : (
              <Text style={styles.cardEmpty}>No check-ins scheduled.</Text>
            )}
          </Card>

          <Card
            testID="card-upcoming-tasks"
            title="Upcoming Tasks"
            icon="list-outline"
            empty="Nothing on your list yet."
            onPress={() => router.push("/tasks")}
          >
            {tasks.length > 0 ? (
              <View style={styles.rowList}>
                {previewTasks.map((t) => {
                  const overdue = !!t.due_date && t.due_date < today;
                  return (
                    <Pressable
                      key={t.id}
                      style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}
                      onPress={() => router.push(`/tasks/${t.id}`)}
                      testID={`upcoming-task-row-${t.id}`}
                    >
                      <Text style={styles.rowTitle} numberOfLines={1}>{t.title}</Text>
                      <View style={styles.rowRight}>
                        {overdue && (
                          <Text style={styles.overdue} testID={`upcoming-task-overdue-${t.id}`}>Overdue</Text>
                        )}
                        <Text style={styles.rowMeta}>{t.due_date || "—"}</Text>
                      </View>
                    </Pressable>
                  );
                })}
                {moreTasks > 0 && (
                  <Text style={styles.moreLine} testID="upcoming-task-more">+{moreTasks} more</Text>
                )}
              </View>
            ) : (
              <Text style={styles.cardEmpty}>Nothing on your list yet.</Text>
            )}
          </Card>

          <Card
            testID="card-recent-checkins"
            title="Recent Check-ins"
            icon="pulse-outline"
            empty="No check-ins today."
            onPress={() => router.push("/(tabs)/timeline")}
          >
            {events.length > 0 ? (
              <View style={styles.eventsPreview}>
                {events.slice(0, 3).map((e) => (
                  <View key={e.id} style={styles.eventRow}>
                    <Text style={styles.eventTime}>{e.time}</Text>
                    <Text style={styles.eventTitle} numberOfLines={1}>{e.title}</Text>
                  </View>
                ))}
                {events.length > 3 && <Text style={styles.eventMore}>+{events.length - 3} more</Text>}
              </View>
            ) : (
              <Text style={styles.cardEmpty}>No check-ins today.</Text>
            )}
          </Card>

          <Card
            testID="card-todays-spending"
            title="Today's Spending"
            icon="cash-outline"
            empty="Quiet spending today."
            onPress={() => router.push("/spending")}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xxxl * 2 },
  hello: { fontSize: 14, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  subhead: { fontFamily: fonts.displayBold, fontSize: 36, color: colors.onSurface, fontWeight: "700", marginTop: spacing.xs, marginBottom: spacing.xl },
  headerRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: spacing.md },
  stack: { gap: spacing.lg },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  cardHeadLeft: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  cardEmpty: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.xs },

  rowList: { gap: spacing.sm, marginTop: spacing.xs },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.xs,
    gap: spacing.md,
  },
  rowTitle: { flex: 1, fontSize: 14, color: colors.onSurface },
  rowMeta: { fontSize: 12, color: colors.onSurfaceSecondary },
  rowRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  overdue: { fontSize: 11, color: colors.error, fontWeight: "700", letterSpacing: 0.5 },
  moreLine: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs },

  eventsPreview: { gap: spacing.sm, marginTop: spacing.xs },
  eventRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  eventTime: { fontSize: 12, color: colors.onSurfaceTertiary, width: 52 },
  eventTitle: { fontSize: 14, color: colors.onSurface, flex: 1 },
  eventMore: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
});
