import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

type Journey = {
  id: string;
  title: string;
  description: string;
  target_completion_date: string;
  status: string;
  created_at: string;
  updated_at: string;
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary,
  archived: colors.onSurfaceTertiary,
};

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "short", month: "long", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

export default function LearningJourneyDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [journey, setJourney] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null); setLoading(true);
    try {
      const j = await api.getLearningJourney(id);
      setJourney(j);
    } catch (e: any) {
      setError(e?.message || "Could not load");
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doDelete = async () => {
    if (!id) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteLearningJourney(id);
      setConfirmOpen(false);
      router.replace("/(tabs)/learn");
    } catch (e: any) {
      setDeleteError(e?.message || "Could not delete");
    } finally { setDeleting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="learn-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {journey && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/learn/edit/${journey.id}`)} testID="learn-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="learn-detail-delete-button" hitSlop={12}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          </View>
        )}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}><Text style={styles.errorText}>{error}</Text></View>
      ) : journey ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.topRow}>
            <Text style={styles.tag}>LEARNING</Text>
            <View style={styles.statusPill}>
              <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[journey.status] || colors.brandPrimary }]} />
              <Text style={styles.statusText}>{journey.status}</Text>
            </View>
          </View>

          <Text style={styles.title} testID="learn-detail-title">{journey.title}</Text>

          {journey.description ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>DESCRIPTION</Text>
              <Text style={styles.blockBody} testID="learn-detail-description">{journey.description}</Text>
            </View>
          ) : null}

          {journey.target_completion_date ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>TARGET COMPLETION</Text>
              <View style={styles.dateRow}>
                <Ionicons name="calendar-outline" size={16} color={colors.onSurfaceSecondary} />
                <Text style={styles.blockBody} testID="learn-detail-target-date">{formatDate(journey.target_completion_date)}</Text>
              </View>
            </View>
          ) : null}
        </ScrollView>
      ) : null}

      <ConfirmModal
        visible={confirmOpen}
        title={`Delete "${journey?.title || "this journey"}"?`}
        message="This will permanently remove this learning journey."
        confirmLabel="Delete" danger busy={deleting} error={deleteError}
        onCancel={() => setConfirmOpen(false)} onConfirm={doDelete}
        testID="learn-delete-modal"
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
  tag: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  block: { marginTop: spacing.xl },
  blockLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginBottom: spacing.xs },
  blockBody: { fontSize: 16, color: colors.onSurface, lineHeight: 24 },
  dateRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
});
