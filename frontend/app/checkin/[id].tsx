import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

export default function CheckinDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [c, setC] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const doc = await api.getCheckin(id);
      setC(doc);
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doDelete = async () => {
    if (!id) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteCheckin(id);
      setConfirmOpen(false);
      router.replace("/(tabs)/timeline");
    } catch (e: any) {
      setDeleteError(e?.message || "Could not delete");
    } finally { setDeleting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="checkin-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {c && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/checkin/edit/${c.id}`)} testID="checkin-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="checkin-detail-delete-button" hitSlop={12}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          </View>
        )}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : c ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.type}>{(c.type || "").toUpperCase()} CHECK-IN</Text>
          <Text style={styles.title} testID="checkin-detail-title">{c.title}</Text>
          <Text style={styles.meta}>{c.date} · {c.time}</Text>
          {c.notes ? <Text style={styles.notes} testID="checkin-detail-notes">{c.notes}</Text> : null}
          {c.attachment ? (
            <View style={styles.block}>
              <Text style={styles.blockLabel}>ATTACHMENT</Text>
              <Text style={styles.blockBody}>{c.attachment}</Text>
            </View>
          ) : null}
          {c.follow_up_task_id ? (
            <Text style={{ color: colors.brandPrimary, marginTop: spacing.lg }} testID="checkin-follow-up-marker">Follow-up task created ↗</Text>
          ) : null}
        </ScrollView>
      ) : null}

      <ConfirmModal
        visible={confirmOpen}
        title="Delete this check-in?"
        message="This will permanently remove the check-in."
        confirmLabel="Delete"
        danger
        busy={deleting}
        error={deleteError}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={doDelete}
        testID="checkin-delete-modal"
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
  type: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  meta: { color: colors.onSurfaceSecondary, fontSize: 13, marginTop: spacing.sm },
  notes: { fontSize: 16, color: colors.onSurface, lineHeight: 24, marginTop: spacing.lg },
  block: { marginTop: spacing.lg },
  blockLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  blockBody: { fontSize: 14, color: colors.onSurface, marginTop: 4 },
  _unused: { borderRadius: radius.pill },
});
