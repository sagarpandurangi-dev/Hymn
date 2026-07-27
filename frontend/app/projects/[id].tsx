import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import type { ActiveDreamPlan } from "@/src/lib/dreams";
import ConfirmModal from "@/src/components/ConfirmModal";

type Project = {
  id: string;
  title: string;
  description: string;
  status: string;
  start_date: string;
  target_end_date: string;
  notes: string;
  checkin_cadence: string;
};

type ProjectTask = {
  id: string;
  title: string;
  due_date: string;
  status: string;
  project_id: string | null;
};

function cadenceLabel(value: string): string {
  if (!value) return "No recurring schedule";
  if (value === "manual") return "Only when you choose";
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}

export default function ProjectDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<ProjectTask[]>([]);
  const [attachedPlan, setAttachedPlan] = useState<ActiveDreamPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    setLoading(true);
    try {
      const [project, allTasks] = await Promise.all([
        api.getProject(id),
        api.listTasks(),
      ]);
      setP(project);
      setTasks(
        allTasks.filter((task) => task.project_id === id),
      );
      try {
        setAttachedPlan(await api.getActiveDreamPlan("project", id));
      } catch {
        setAttachedPlan(null);
      }
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : "Could not load this project.");
    }
    finally { setLoading(false); }
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
      ) : loadError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{loadError}</Text>
          <Pressable onPress={load} style={styles.retryButton} testID="project-detail-retry">
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
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
          <Text style={styles.definition}>
            A project is bounded work that helps you move toward a result.
          </Text>

          <Pressable
            onPress={() => router.push(`/dreams/new?sourceType=project&sourceId=${p.id}`)}
            testID="project-detail-plan-btn"
            style={styles.planBtn}
          >
            <Ionicons name="git-network-outline" size={18} color={colors.onBrandPrimary} />
            <Text style={styles.planBtnText}>Plan with Hymn</Text>
          </Pressable>

          <View style={styles.progressActions}>
            <Pressable
              onPress={() => router.push(`/checkin/project?projectId=${p.id}`)}
              testID="project-detail-log-progress"
              style={styles.secondaryAction}
            >
              <Ionicons name="pulse-outline" size={18} color={colors.brandPrimary} />
              <View style={styles.actionCopy}>
                <Text style={styles.secondaryActionTitle}>Log progress</Text>
                <Text style={styles.secondaryActionDetail}>Record what changed today.</Text>
              </View>
            </Pressable>
            <Pressable
              onPress={() => router.push({
                pathname: "/checkin-schedule/[targetType]/[targetId]",
                params: { targetType: "project", targetId: p.id },
              })}
              testID="project-detail-set-checkin-schedule"
              style={styles.secondaryAction}
            >
              <Ionicons name="calendar-outline" size={18} color={colors.brandPrimary} />
              <View style={styles.actionCopy}>
                <Text style={styles.secondaryActionTitle}>Set check-in schedule</Text>
                <Text style={styles.secondaryActionDetail}>
                  {cadenceLabel(p.checkin_cadence)}
                </Text>
              </View>
            </Pressable>
          </View>

          {attachedPlan?.attached ? (
            <Pressable
              onPress={() => router.push(`/dreams/${attachedPlan.proposal_id}`)}
              style={styles.attachedPlan}
              testID="project-detail-attached-plan"
            >
              <View style={styles.attachedPlanHeading}>
                <Ionicons name="checkmark-circle" size={20} color={colors.success} />
                <Text style={styles.attachedPlanTitle}>Plan attached</Text>
              </View>
              <Text style={styles.attachedPlanDetail}>
                {attachedPlan.nodes.length} accepted map items are attached to this project.
              </Text>
              <Text style={styles.attachedPlanLink}>Review plan</Text>
            </Pressable>
          ) : null}

          <View style={styles.section}>
            <Text style={styles.sectionLabel}>PROJECT TASKS</Text>
            {tasks.length === 0 ? (
              <Text style={styles.emptyText}>No tasks are attached yet.</Text>
            ) : (
              tasks.map((task) => (
                <Pressable
                  key={task.id}
                  onPress={() => router.push(`/tasks/${task.id}`)}
                  style={styles.taskRow}
                  testID={`project-detail-task-${task.id}`}
                >
                  <Ionicons
                    name={task.status === "done" ? "checkmark-circle" : "ellipse-outline"}
                    size={18}
                    color={task.status === "done" ? colors.success : colors.onSurfaceTertiary}
                  />
                  <Text style={styles.taskTitle} numberOfLines={1}>{task.title}</Text>
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
  errorText: { color: colors.error, fontSize: 14, textAlign: "center" },
  retryButton: { borderColor: colors.brandPrimary, borderRadius: radius.md, borderWidth: 1, marginTop: spacing.lg, paddingHorizontal: spacing.xl, paddingVertical: spacing.md },
  retryText: { color: colors.brandPrimary, fontSize: 14, fontWeight: "600" },
  status: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  desc: { fontSize: 15, color: colors.onSurfaceSecondary, marginTop: spacing.md },
  dates: { color: colors.onSurfaceSecondary, fontSize: 13, marginTop: spacing.md },
  notes: { fontSize: 15, color: colors.onSurface, marginTop: spacing.lg, lineHeight: 24 },
  definition: { color: colors.onSurfaceTertiary, fontSize: 12, lineHeight: 18, marginTop: spacing.lg },
  planBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, backgroundColor: colors.brandPrimary,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg,
    borderRadius: radius.md, marginTop: spacing.lg,
  },
  planBtnText: { color: colors.onBrandPrimary, fontFamily: fonts.displayBold, fontSize: 14 },
  progressActions: { gap: spacing.sm, marginTop: spacing.md },
  secondaryAction: {
    alignItems: "center", borderColor: colors.borderStrong, borderRadius: radius.md,
    borderWidth: 1, flexDirection: "row", gap: spacing.md, padding: spacing.md,
  },
  actionCopy: { flex: 1 },
  secondaryActionTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  secondaryActionDetail: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },
  attachedPlan: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    marginTop: spacing.lg, padding: spacing.lg,
  },
  attachedPlanHeading: { alignItems: "center", flexDirection: "row", gap: spacing.sm },
  attachedPlanTitle: { color: colors.onSurface, fontSize: 15, fontWeight: "600" },
  attachedPlanDetail: { color: colors.onSurfaceSecondary, fontSize: 13, lineHeight: 19, marginTop: spacing.sm },
  attachedPlanLink: { color: colors.brandPrimary, fontSize: 13, fontWeight: "600", marginTop: spacing.sm },
  section: { marginTop: spacing.xl },
  sectionLabel: { color: colors.onSurfaceTertiary, fontSize: 10, letterSpacing: 1.5 },
  emptyText: { color: colors.onSurfaceTertiary, fontSize: 13, marginTop: spacing.sm },
  taskRow: {
    alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, padding: spacing.md,
  },
  taskTitle: { color: colors.onSurface, flex: 1, fontSize: 14 },
  _u: { borderRadius: radius.pill },
});
