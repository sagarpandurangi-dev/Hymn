import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

type Goal = {
  id: string; title: string; domain_id: string; domain_name: string;
  target_outcome: string; deadline: string; status: string; notes: string;
  expected_outcomes_total: number; expected_outcomes_completed: number; completion_pct: number;
};

type EO = {
  id: string; title: string; target_value: string; current_value: string; unit: string;
  deadline: string; status: string; notes: string;
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary, paused: colors.warning, completed: colors.success, abandoned: colors.onSurfaceTertiary,
};

export default function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [goal, setGoal] = useState<Goal | null>(null);
  const [eos, setEos] = useState<EO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirmEOFor, setConfirmEOFor] = useState<EO | null>(null);
  const [deletingEO, setDeletingEO] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null); setLoading(true);
    try {
      const g = await api.getGoal(id);
      setGoal(g);
      const list = await api.listExpectedOutcomes(id);
      setEos(list);
    } catch (e: any) {
      setError(e?.message || "Could not load");
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doDelete = async () => {
    if (!id) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteGoal(id);
      setConfirmOpen(false);
      router.replace("/goals");
    } catch (e: any) {
      setDeleteError(e?.message || "Could not delete");
    } finally { setDeleting(false); }
  };

  const doDeleteEO = async () => {
    if (!confirmEOFor) return;
    setDeletingEO(true);
    try {
      await api.deleteExpectedOutcome(confirmEOFor.id);
      setConfirmEOFor(null);
      await load();
    } finally { setDeletingEO(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="goal-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {goal && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/goals/edit/${goal.id}`)} testID="goal-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="goal-detail-delete-button" hitSlop={12}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          </View>
        )}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}><Text style={styles.errorText}>{error}</Text></View>
      ) : goal ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.topRow}>
            <Text style={styles.domain}>{(goal.domain_name || "—").toUpperCase()}</Text>
            <View style={styles.statusPill}>
              <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[goal.status] || colors.brandPrimary }]} />
              <Text style={styles.statusText}>{goal.status}</Text>
            </View>
          </View>

          <Text style={styles.title} testID="goal-detail-title">{goal.title}</Text>

          {/* Progress summary */}
          <View style={styles.progressBlock} testID="goal-detail-progress">
            <Text style={styles.blockLabel}>PROGRESS</Text>
            <Text style={styles.progressText}>
              <Text style={styles.progressBig}>{goal.expected_outcomes_completed}</Text>
              <Text style={styles.progressBig}> / {goal.expected_outcomes_total}</Text>
              <Text style={styles.progressSmall}>  ·  {goal.completion_pct}%</Text>
            </Text>
            <View style={styles.progressBarTrack}>
              <View style={[styles.progressBarFill, { width: `${Math.min(goal.completion_pct, 100)}%` }]} />
            </View>
          </View>

          {/* Expected Outcomes list */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.blockLabel}>EXPECTED OUTCOMES</Text>
              <Pressable
                onPress={() => router.push(`/expected-outcomes/add?goalId=${goal.id}`)}
                testID="goal-detail-add-eo"
                hitSlop={8}
                disabled={eos.length >= 7}
                style={eos.length >= 7 ? { opacity: 0.4 } : undefined}
              >
                <Ionicons name="add-circle-outline" size={22} color={colors.brandPrimary} />
              </Pressable>
            </View>
            {eos.length >= 7 && <Text style={styles.limitText}>Max 7 expected outcomes per goal.</Text>}
            {eos.length === 0 ? (
              <Text style={styles.emptyLine}>No expected outcomes yet.</Text>
            ) : (
              eos.map((eo) => (
                <View key={eo.id} style={styles.eoRow} testID={`eo-row-${eo.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.eoTitle}>{eo.title}</Text>
                    <Text style={styles.eoMeta}>
                      {(eo.current_value || "0")}/{eo.target_value || "—"} {eo.unit ? eo.unit : ""} · {eo.status}
                    </Text>
                  </View>
                  <Pressable onPress={() => router.push(`/expected-outcomes/edit/${eo.id}`)} hitSlop={8} testID={`eo-edit-${eo.id}`} style={styles.iconBtn}>
                    <Ionicons name="pencil-outline" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                  <Pressable onPress={() => setConfirmEOFor(eo)} hitSlop={8} testID={`eo-delete-${eo.id}`} style={styles.iconBtn}>
                    <Ionicons name="trash-outline" size={18} color={colors.error} />
                  </Pressable>
                </View>
              ))
            )}
          </View>

          {goal.target_outcome ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>NARRATIVE TARGET</Text>
              <Text style={styles.blockBody} testID="goal-detail-target">{goal.target_outcome}</Text>
            </View>
          ) : null}
          {goal.deadline ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>DEADLINE</Text>
              <Text style={styles.blockBody} testID="goal-detail-deadline">{goal.deadline}</Text>
            </View>
          ) : null}
          {goal.notes ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>NOTES</Text>
              <Text style={styles.notes} testID="goal-detail-notes">{goal.notes}</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : null}

      <ConfirmModal
        visible={confirmOpen}
        title={`Delete "${goal?.title || "this goal"}"?`}
        message="This will remove the goal and all its expected outcomes."
        confirmLabel="Delete" danger busy={deleting} error={deleteError}
        onCancel={() => setConfirmOpen(false)} onConfirm={doDelete}
        testID="goal-delete-modal"
      />
      <ConfirmModal
        visible={!!confirmEOFor}
        title={`Delete "${confirmEOFor?.title || "outcome"}"?`}
        message="This will remove this expected outcome."
        confirmLabel="Delete" danger busy={deletingEO}
        onCancel={() => setConfirmEOFor(null)} onConfirm={doDeleteEO}
        testID="eo-delete-modal"
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
  errorText: { color: colors.error },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.md },
  domain: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  progressBlock: { marginTop: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  progressText: { marginTop: 6 },
  progressBig: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, fontWeight: "700" },
  progressSmall: { fontSize: 13, color: colors.onSurfaceSecondary },
  progressBarTrack: { height: 6, backgroundColor: colors.surfaceTertiary, borderRadius: 3, marginTop: spacing.md, overflow: "hidden" },
  progressBarFill: { height: 6, backgroundColor: colors.brandPrimary },
  section: { marginTop: spacing.xl },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  block: { marginTop: spacing.xl },
  blockLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  blockBody: { fontSize: 16, color: colors.onSurface, lineHeight: 24, marginTop: spacing.xs },
  notes: { fontSize: 15, color: colors.onSurface, lineHeight: 24, marginTop: spacing.xs },
  emptyLine: { color: colors.onSurfaceTertiary, fontSize: 13, marginTop: spacing.xs },
  limitText: { color: colors.warning, fontSize: 12, marginBottom: spacing.xs },
  eoRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.sm },
  eoTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  eoMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  iconBtn: { padding: 4 },
});
