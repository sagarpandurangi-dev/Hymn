import { useCallback, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type EventItem = {
  id: string; type: string; title: string; date: string; time: string; notes: string; created_at: string; updated_at: string;
};

function formatDate(d: string) {
  try {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  } catch { return d; }
}

export default function EventDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [event, setEvent] = useState<EventItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null); setLoading(true);
    try {
      const e = await api.getEvent(id);
      setEvent(e);
    } catch (e: any) {
      setError(e?.message || "Could not load event");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onConfirmDelete = async () => {
    if (!id) return;
    setDeleteError(null);
    setDeleting(true);
    try {
      await api.deleteEvent(id);
      setConfirmOpen(false);
      // Navigate back to Timeline; useFocusEffect there will refresh the list.
      router.replace("/(tabs)/timeline");
    } catch (e: any) {
      setDeleteError(e?.message || "Could not delete");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="event-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {event && (
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push(`/event/edit/${event.id}`)} testID="event-detail-edit-button" hitSlop={12}>
              <Text style={styles.edit}>Edit</Text>
            </Pressable>
            <Pressable onPress={() => setConfirmOpen(true)} testID="event-detail-delete-button" hitSlop={12}>
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
          <Pressable style={styles.retry} onPress={load} testID="event-detail-retry"><Text style={styles.retryText}>Retry</Text></Pressable>
        </View>
      ) : event ? (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.type}>{event.type.toUpperCase()}</Text>
          <Text style={styles.title} testID="event-detail-title">{event.title}</Text>
          <View style={styles.metaRow}>
            <View style={styles.metaItem}>
              <Ionicons name="calendar-outline" size={14} color={colors.onSurfaceSecondary} />
              <Text style={styles.metaText}>{formatDate(event.date)}</Text>
            </View>
            <View style={styles.metaItem}>
              <Ionicons name="time-outline" size={14} color={colors.onSurfaceSecondary} />
              <Text style={styles.metaText}>{event.time}</Text>
            </View>
          </View>

          {event.notes ? (
            <View style={styles.notesBlock}>
              <Text style={styles.notes} testID="event-detail-notes">{event.notes}</Text>
            </View>
          ) : (
            <Text style={styles.emptyNotes}>No notes for this event.</Text>
          )}
        </ScrollView>
      ) : null}

      <Modal
        visible={confirmOpen}
        transparent
        animationType="fade"
        onRequestClose={() => (deleting ? null : setConfirmOpen(false))}
      >
        <View style={styles.modalBackdrop} testID="delete-confirm-modal">
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Delete this event?</Text>
            <Text style={styles.modalBody}>
              This will remove &quot;{event?.title || "the event"}&quot; permanently.
            </Text>
            {deleteError ? <Text style={styles.deleteError} testID="delete-error">{deleteError}</Text> : null}
            <View style={styles.modalButtonRow}>
              <Pressable
                style={[styles.modalBtn, styles.modalBtnSecondary]}
                onPress={() => setConfirmOpen(false)}
                disabled={deleting}
                testID="delete-cancel-button"
              >
                <Text style={styles.modalBtnSecondaryText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalBtn, styles.modalBtnDanger, deleting && styles.modalBtnDisabled]}
                onPress={onConfirmDelete}
                disabled={deleting}
                testID="delete-confirm-button"
              >
                {deleting ? (
                  <ActivityIndicator color={colors.onError} />
                ) : (
                  <Text style={styles.modalBtnDangerText}>Delete</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  edit: { color: colors.brandPrimary, fontSize: 15, fontWeight: "600" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  type: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 30, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 40 },
  metaRow: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.lg, marginBottom: spacing.xl },
  metaItem: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  metaText: { color: colors.onSurfaceSecondary, fontSize: 13 },
  notesBlock: { paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  notes: { fontSize: 16, color: colors.onSurface, lineHeight: 26 },
  emptyNotes: { color: colors.onSurfaceTertiary, fontSize: 14, fontStyle: "italic", marginTop: spacing.md },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  retryText: { color: colors.onSurface },
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(30,30,28,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.xl,
  },
  modalCard: {
    width: "100%", maxWidth: 360, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: spacing.xl,
  },
  modalTitle: { fontFamily: fonts.displayBold, fontSize: 20, color: colors.onSurface, fontWeight: "700", marginBottom: spacing.sm },
  modalBody: { fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  deleteError: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  modalButtonRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xl },
  modalBtn: {
    flex: 1, paddingVertical: spacing.md + 2, borderRadius: radius.pill,
    alignItems: "center", justifyContent: "center",
  },
  modalBtnSecondary: { backgroundColor: colors.surfaceSecondary },
  modalBtnSecondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "500" },
  modalBtnDanger: { backgroundColor: colors.error },
  modalBtnDangerText: { color: colors.onError, fontSize: 15, fontWeight: "600" },
  modalBtnDisabled: { opacity: 0.7 },
});
