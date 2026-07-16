import { useCallback, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";
import { formatMoney, stateLabel } from "@/src/lib/finance/format";

export default function TaskDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [t, setT] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // §12 — linked Financial Commitment prompt
  const [linkedCommitment, setLinkedCommitment] = useState<any | null>(null);
  const [promptOpen, setPromptOpen] = useState(false);

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

  /**
   * §12 — When a task with a linked Financial Commitment is marked done we
   * MUST NOT auto-complete the commitment. Instead prompt the user with
   * the three options: Complete FC / Keep FC Active / Remind Later.
   */
  const onMarkDone = async () => {
    if (!id) return;
    try {
      const fc = await api.getTaskLinkedCommitment(id);
      if (fc && (fc.state === "reserved" || fc.state === "expired" || fc.state === "draft")) {
        setLinkedCommitment(fc);
        setPromptOpen(true);
        // Mark task done in the background — the commitment path is decided independently.
        await mark({ status: "done" });
        return;
      }
    } catch { /* ignore — task marks done regardless */ }
    await mark({ status: "done" });
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
              <Pressable onPress={onMarkDone} style={[styles.actionBtn, { backgroundColor: colors.success }]} testID="task-detail-done-button">
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

      {/* §12 — linked Financial Commitment prompt */}
      <Modal visible={promptOpen} animationType="slide" transparent onRequestClose={() => setPromptOpen(false)}>
        <View style={sheetStyles.wrap}>
          <View style={sheetStyles.card}>
            <Text style={sheetStyles.title}>You completed the linked Task.</Text>
            <Text style={sheetStyles.body}>Did this also complete the Financial Commitment?</Text>
            {linkedCommitment && (
              <View style={sheetStyles.fcCard}>
                <Text style={sheetStyles.fcTitle}>{linkedCommitment.title} · {stateLabel(linkedCommitment.state)}</Text>
                <Text style={sheetStyles.fcMeta}>{linkedCommitment.currency} {formatMoney(linkedCommitment.amount)} · due {linkedCommitment.due_date}</Text>
              </View>
            )}
            <Text style={sheetStyles.warning}>
              Completing this Financial Commitment will record the actual spend, consume the amount spent, release only
              unused reserved money, return the unused amount to the available pool, recalculate your forecasts and
              preserve the full history.
            </Text>
            <Pressable
              style={sheetStyles.primary}
              onPress={() => { setPromptOpen(false); router.push(`/finance/commitments/${linkedCommitment.id}`); }}
              testID="task-fc-complete"
            >
              <Text style={sheetStyles.primaryText}>Complete Financial Commitment</Text>
            </Pressable>
            <Pressable style={sheetStyles.secondary} onPress={() => setPromptOpen(false)} testID="task-fc-keep">
              <Text style={sheetStyles.secondaryText}>Keep Financial Commitment Active</Text>
            </Pressable>
            <Pressable style={sheetStyles.secondary} onPress={() => setPromptOpen(false)} testID="task-fc-remind">
              <Text style={sheetStyles.secondaryText}>Remind Me Later</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const sheetStyles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  card: { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  title: { fontSize: 18, fontWeight: "700", color: colors.onSurface },
  body: { fontSize: 14, color: colors.onSurfaceSecondary },
  fcCard: { padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: 12 },
  fcTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  fcMeta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  warning: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18, fontStyle: "italic" },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: 999, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, borderRadius: 999, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
});

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
