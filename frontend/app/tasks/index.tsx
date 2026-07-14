import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
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
import DateTimeField from "@/src/components/DateTimeField";

type Task = {
  id: string;
  title: string;
  status: string;
  priority: string;
  due_date: string;
  origin: string;
  deferred_until?: string | null;
  original_due_date?: string | null;
  defer_count?: number;
};

const STATUS_COLORS: Record<string, string> = {
  todo: colors.brandPrimary,
  done: colors.success,
  deferred: colors.warning,
};

const MAX_DEFERS = 3;
const MAX_DEFER_DAYS = 14;

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const localTodayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const addDaysISO = (iso: string, days: number) => {
  const [y, m, d] = iso.split("-").map((s) => parseInt(s, 10));
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + days);
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
};

export default function TasksScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [deferTarget, setDeferTarget] = useState<Task | null>(null);
  const [deferDate, setDeferDate] = useState<string>("");
  const [deferError, setDeferError] = useState<string | null>(null);
  const [deferring, setDeferring] = useState(false);

  const load = useCallback(async () => {
    try {
      // Completed / cancelled tasks stay hidden from this list — check-ins on
      // Goals now surface progress separately, so the tasks homepage is only
      // for open work.
      const items = await api.listTasks({ includeCompleted: false });
      setTasks(items);
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const { due, deferred } = useMemo(() => {
    const today = localTodayISO();
    const dueList: Task[] = [];
    const defList: Task[] = [];
    for (const t of tasks) {
      // A task is considered "deferred" when it either has an explicit
      // deferred_until >= today or its status is `deferred` in the DB.
      const isDeferred = (t.deferred_until && t.deferred_until >= today) || t.status === "deferred";
      if (isDeferred) defList.push(t); else dueList.push(t);
    }
    const bucket = (t: Task) => {
      if (!t.due_date) return 3;
      if (t.due_date < today) return 0;
      if (t.due_date === today) return 1;
      return 2;
    };
    dueList.sort((a, b) => {
      const ba = bucket(a); const bb = bucket(b);
      if (ba !== bb) return ba - bb;
      const dc = (a.due_date || "").localeCompare(b.due_date || "");
      if (dc !== 0) return dc;
      return a.title.localeCompare(b.title);
    });
    defList.sort((a, b) => (a.deferred_until || "").localeCompare(b.deferred_until || ""));
    return { due: dueList, deferred: defList };
  }, [tasks]);

  const openDefer = (t: Task) => {
    setDeferTarget(t);
    setDeferError(null);
    const baseline = t.original_due_date || t.due_date || localTodayISO();
    // Suggest tomorrow (from today) as the initial defer date.
    setDeferDate(addDaysISO(localTodayISO(), 1));
    // Prefetch nothing else — the cap message shows dynamically inside modal.
    void baseline;
  };

  const submitDefer = async () => {
    if (!deferTarget) return;
    setDeferError(null);
    setDeferring(true);
    try {
      await api.deferTask(deferTarget.id, deferDate);
      setDeferTarget(null);
      await load();
    } catch (e: any) {
      setDeferError(e?.message || "Could not defer task");
    } finally {
      setDeferring(false);
    }
  };

  const complete = async (id: string) => {
    try { await api.updateTask(id, { status: "done" }); await load(); } catch { /* ignore */ }
  };

  const deferCap = useMemo(() => {
    if (!deferTarget) return null;
    const baseline = deferTarget.original_due_date || deferTarget.due_date || localTodayISO();
    return {
      baseline,
      max: addDaysISO(baseline, MAX_DEFER_DAYS),
      countLeft: MAX_DEFERS - (deferTarget.defer_count || 0),
    };
  }, [deferTarget]);

  const canDeferMore = (t: Task) => (t.defer_count || 0) < MAX_DEFERS && t.status !== "done" && t.status !== "cancelled";

  const renderTaskRow = (t: Task, inDeferredList: boolean) => (
    <Pressable
      key={t.id}
      onPress={() => router.push(`/tasks/${t.id}`)}
      style={styles.card}
      testID={`task-row-${t.id}`}
    >
      <View style={{ flex: 1 }}>
        <View style={styles.top}>
          <View style={styles.pill}>
            <View style={[styles.dot, { backgroundColor: STATUS_COLORS[t.status] || colors.brandPrimary }]} />
            <Text style={styles.pillText}>{inDeferredList ? "deferred" : t.status}</Text>
          </View>
          <Text style={styles.priority}>{(t.priority || "").toUpperCase()}</Text>
        </View>
        <Text style={styles.title} numberOfLines={2}>{t.title}</Text>
        {inDeferredList && t.deferred_until ? (
          <Text style={styles.meta}>
            deferred to {t.deferred_until} · {t.defer_count || 0}/{MAX_DEFERS} defers used
          </Text>
        ) : t.due_date ? (
          <Text style={styles.meta}>due {t.due_date}</Text>
        ) : null}
      </View>
      <Pressable
        hitSlop={8}
        onPress={(e) => { e.stopPropagation(); complete(t.id); }}
        testID={`task-done-${t.id}`}
      >
        <Ionicons name="checkmark-circle-outline" size={26} color={colors.success} />
      </Pressable>
      {canDeferMore(t) && (
        <Pressable
          hitSlop={8}
          onPress={(e) => { e.stopPropagation(); openDefer(t); }}
          testID={`task-defer-${t.id}`}
        >
          <Ionicons name="time-outline" size={22} color={colors.warning} />
        </Pressable>
      )}
    </Pressable>
  );

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
      ) : due.length === 0 && deferred.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="list-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No open tasks.</Text>
          <Pressable onPress={() => router.push("/tasks/add")} style={styles.emptyCta} testID="tasks-empty-add-button">
            <Text style={styles.emptyCtaText}>Add task</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <Text style={styles.sectionHead} testID="tasks-section-due">Due</Text>
          {due.length === 0 ? (
            <Text style={styles.sectionEmpty}>Nothing due right now.</Text>
          ) : (
            due.map((t) => renderTaskRow(t, false))
          )}

          <Text style={[styles.sectionHead, { marginTop: spacing.xl }]} testID="tasks-section-deferred">Deferred</Text>
          {deferred.length === 0 ? (
            <Text style={styles.sectionEmpty}>Nothing deferred.</Text>
          ) : (
            deferred.map((t) => renderTaskRow(t, true))
          )}
        </ScrollView>
      )}

      <Modal visible={!!deferTarget} animationType="slide" transparent onRequestClose={() => setDeferTarget(null)}>
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>Defer task</Text>
              <Pressable onPress={() => setDeferTarget(null)} hitSlop={12} testID="task-defer-close">
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {deferTarget && (
              <>
                <Text style={styles.modalBody} numberOfLines={2}>{deferTarget.title}</Text>
                <Text style={styles.modalMeta}>
                  {(deferTarget.defer_count || 0)}/{MAX_DEFERS} defers used
                  {deferCap ? ` · latest allowed date ${deferCap.max}` : ""}
                </Text>
                <Text style={styles.label}>New date</Text>
                <DateTimeField
                  mode="date"
                  value={deferDate}
                  onChange={setDeferDate}
                  testID="task-defer-date"
                />
                {deferError && <Text style={styles.errorText} testID="task-defer-error">{deferError}</Text>}
                <Pressable
                  style={[styles.cta, deferring && { opacity: 0.5 }]}
                  disabled={deferring}
                  onPress={submitDefer}
                  testID="task-defer-submit"
                >
                  <Text style={styles.ctaText}>{deferring ? "Deferring…" : "Defer"}</Text>
                </Pressable>
              </>
            )}
          </View>
        </View>
      </Modal>
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
  sectionHead: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 1.2, fontWeight: "700", textTransform: "uppercase", marginBottom: spacing.xs },
  sectionEmpty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", marginBottom: spacing.sm },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  priority: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1 },
  title: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  modalWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.surface, padding: spacing.xl, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, gap: spacing.sm, ...(Platform.OS === "ios" ? { paddingBottom: spacing.xxxl } : {}) },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  modalTitle: { fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  modalBody: { fontSize: 15, color: colors.onSurface, marginTop: spacing.xs },
  modalMeta: { fontSize: 12, color: colors.onSurfaceSecondary },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, letterSpacing: 0.5 },
  errorText: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", marginTop: spacing.lg },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});

// Silence unused Alert import — kept for future confirmation flows.
void Alert;
