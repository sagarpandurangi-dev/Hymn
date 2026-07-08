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
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary,
  paused: colors.warning,
  completed: colors.success,
  abandoned: colors.onSurfaceTertiary,
};

export default function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [goal, setGoal] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null); setLoading(true);
    try {
      const g = await api.getGoal(id);
      setGoal(g);
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
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} style={styles.retry}><Text style={styles.retryText}>Retry</Text></Pressable>
        </View>
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

          {goal.target_outcome ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>TARGET OUTCOME</Text>
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
        message="This will permanently remove this goal."
        confirmLabel="Delete"
        danger
        busy={deleting}
        error={deleteError}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={doDelete}
        testID="goal-delete-modal"
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
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  retryText: { color: colors.onSurface },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.md },
  domain: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  title: { fontFamily: fonts.displayBold, fontSize: 30, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 40 },
  block: { marginTop: spacing.xl },
  blockLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginBottom: spacing.xs },
  blockBody: { fontSize: 16, color: colors.onSurface, lineHeight: 24 },
  notes: { fontSize: 15, color: colors.onSurface, lineHeight: 24 },
});
