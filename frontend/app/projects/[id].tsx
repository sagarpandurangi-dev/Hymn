import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";
import { TaskListWithGrouping } from "@/src/components/TaskListWithGrouping";

type Task = {
  id: string; title: string; due_date: string; priority: string; status: string;
};

type Checkin = {
  id: string; type: string; title: string; date: string; time: string; notes: string;
};

function formatDateShort(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch { return iso; }
}

export default function ProjectDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<any>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [checkins, setCheckins] = useState<Checkin[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [pr, ts, cs] = await Promise.all([
        api.getProject(id),
        api.listTasks({ projectId: id }),
        api.listCheckins({ projectId: id }),
      ]);
      setP(pr);
      setTasks(ts as Task[]);
      setCheckins(cs as Checkin[]);
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doDelete = async () => {
    if (!id) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteProject(id);
      setConfirmOpen(false);
      router.replace("/projects");
    } catch (e: any) { setDeleteError(e?.message || "Could not delete"); }
    finally { setDeleting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="project-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {p && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/projects/edit/${p.id}`)} testID="project-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="project-detail-delete-button" hitSlop={12}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          </View>
        )}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : p ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.status}>{(p.status || "").toUpperCase()}</Text>
          <Text style={styles.title} testID="project-detail-title">{p.title}</Text>
          {p.description ? <Text style={styles.desc}>{p.description}</Text> : null}
          {(p.start_date || p.target_end_date) ? (
            <Text style={styles.dates}>
              {p.start_date || "—"}{" → "}{p.target_end_date || "—"}
            </Text>
          ) : null}
          {p.notes ? <Text style={styles.notes} testID="project-detail-notes">{p.notes}</Text> : null}

          <Pressable
            onPress={() => router.push(`/planning/project/${p.id}`)}
            testID="project-detail-plan-btn"
            style={styles.planBtn}
          >
            <Ionicons name="git-network-outline" size={18} color={colors.onBrandPrimary} />
            <Text style={styles.planBtnText}>Plan with Hymn</Text>
          </Pressable>

          {/* ── TASKS ── */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.blockLabel}>TASKS</Text>
              <Pressable
                onPress={() => router.push(`/tasks/add?projectId=${p.id}`)}
                testID="project-detail-add-task"
                hitSlop={8}
              >
                <Ionicons name="add-circle-outline" size={22} color={colors.brandPrimary} />
              </Pressable>
            </View>
            <TaskListWithGrouping
              tasks={tasks}
              onOpenTask={(tid) => router.push(`/tasks/${tid}`)}
              onChanged={load}
              testIDPrefix="task"
              emptyText="No tasks yet."
            />
          </View>

          {/* ── CHECK-INS ── */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.blockLabel}>CHECK-INS</Text>
              <Pressable
                onPress={() => router.push("/checkin/project")}
                testID="project-detail-add-checkin"
                hitSlop={8}
              >
                <Ionicons name="add-circle-outline" size={22} color={colors.brandPrimary} />
              </Pressable>
            </View>
            {checkins.length === 0 ? (
              <Text style={styles.emptyLine}>No check-ins yet.</Text>
            ) : (
              checkins.slice(0, 20).map((c) => (
                <Pressable
                  key={c.id}
                  onPress={() => router.push(`/checkin/${c.id}`)}
                  style={styles.checkinRow}
                  testID={`checkin-row-${c.id}`}
                >
                  <View style={styles.checkinDot} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={1}>{c.title || "(untitled)"}</Text>
                    <Text style={styles.rowMeta}>{formatDateShort(c.date)}{c.time ? ` · ${c.time}` : ""}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
                </Pressable>
              ))
            )}
          </View>
        </ScrollView>
      ) : null}

      <ConfirmModal
        visible={confirmOpen}
        title={`Delete "${p?.title || "this project"}"?`}
        message="This will permanently remove this project."
        confirmLabel="Delete" danger busy={deleting} error={deleteError}
        onCancel={() => setConfirmOpen(false)} onConfirm={doDelete}
        testID="project-delete-modal"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  edit: { color: colors.brandPrimary, fontSize: 15, fontWeight: "600" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  status: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  desc: { fontSize: 15, color: colors.onSurfaceSecondary, marginTop: spacing.md },
  dates: { color: colors.onSurfaceSecondary, fontSize: 13, marginTop: spacing.md },
  notes: { fontSize: 15, color: colors.onSurface, marginTop: spacing.lg, lineHeight: 24 },
  planBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, backgroundColor: colors.brandPrimary,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg,
    borderRadius: radius.md, marginTop: spacing.lg,
  },
  planBtnText: { color: colors.onBrandPrimary, fontFamily: fonts.displayBold, fontSize: 14 },
  section: { marginTop: spacing.xl },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  blockLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  emptyLine: { color: colors.onSurfaceTertiary, fontSize: 13, marginTop: spacing.xs },
  checkinRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.sm,
  },
  checkinDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary },
  rowTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
});
