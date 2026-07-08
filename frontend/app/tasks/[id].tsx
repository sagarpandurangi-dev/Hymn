import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

export default function TaskDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [t, setT] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try { setT(await api.getTask(id)); } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doDelete = async () => {
    if (!id) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteTask(id);
      setConfirmOpen(false);
      router.replace("/tasks");
    } catch (e: any) { setDeleteError(e?.message || "Could not delete"); }
    finally { setDeleting(false); }
  };

  const mark = async (patch: any) => {
    if (!id) return;
    await api.updateTask(id, patch);
    await load();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="task-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {t && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/tasks/edit/${t.id}`)} testID="task-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="task-detail-delete-button" hitSlop={12}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          </View>
        )}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : t ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.meta}>{(t.status || "").toUpperCase()} · {(t.priority || "").toUpperCase()} · from {t.origin}</Text>
          <Text style={styles.title} testID="task-detail-title">{t.title}</Text>
          {t.due_date ? <Text style={styles.due}>due {t.due_date}</Text> : null}
          {t.assigned_to_type === "external" ? (
            <Text style={styles.due} testID="task-detail-assignee">
              Assigned to {t.assigned_to_name || t.assigned_to_phone}
              {t.assigned_to_phone && t.assigned_to_name ? ` · ${t.assigned_to_phone}` : ""}
            </Text>
          ) : (
            <Text style={styles.due} testID="task-detail-assignee">Assigned to you</Text>
          )}
          {t.notes ? <Text style={styles.notes} testID="task-detail-notes">{t.notes}</Text> : null}

          <View style={styles.actionsRow}>
            {t.status !== "done" && (
              <Pressable onPress={() => mark({ status: "done" })} style={[styles.actionBtn, { backgroundColor: colors.success }]} testID="task-detail-done-button">
                <Ionicons name="checkmark" size={18} color="#fff" />
                <Text style={styles.actionText}>Done</Text>
              </Pressable>
            )}
            {t.status !== "deferred" && t.status !== "done" && (
              <Pressable onPress={() => mark({ status: "deferred" })} style={[styles.actionBtn, { backgroundColor: colors.warning }]} testID="task-detail-defer-button">
                <Ionicons name="time-outline" size={18} color="#fff" />
                <Text style={styles.actionText}>Defer</Text>
              </Pressable>
            )}
            {t.status !== "todo" && (
              <Pressable onPress={() => mark({ status: "todo" })} style={[styles.actionBtn, { backgroundColor: colors.brandPrimary }]} testID="task-detail-reopen-button">
                <Ionicons name="refresh" size={18} color="#fff" />
                <Text style={styles.actionText}>Reopen</Text>
              </Pressable>
            )}
          </View>
        </ScrollView>
      ) : null}

      <ConfirmModal
        visible={confirmOpen}
        title={`Delete "${t?.title || "this task"}"?`}
        message="This will permanently remove the task."
        confirmLabel="Delete" danger busy={deleting} error={deleteError}
        onCancel={() => setConfirmOpen(false)} onConfirm={doDelete}
        testID="task-delete-modal"
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
  meta: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 34 },
  due: { color: colors.onSurfaceSecondary, fontSize: 13, marginTop: spacing.sm },
  notes: { fontSize: 15, color: colors.onSurface, marginTop: spacing.lg, lineHeight: 24 },
  actionsRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xl, flexWrap: "wrap" },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderRadius: 999 },
  actionText: { color: "#fff", fontWeight: "600", fontSize: 14 },
});
