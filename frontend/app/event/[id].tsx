import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
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

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="event-detail-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        {event && (
          <Pressable onPress={() => router.push(`/event/edit/${event.id}`)} testID="event-detail-edit-button" hitSlop={12}>
            <Text style={styles.edit}>Edit</Text>
          </Pressable>
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
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
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
});
