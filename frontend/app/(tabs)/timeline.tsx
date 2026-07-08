import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type EventItem = {
  id: string;
  type: string;
  title: string;
  date: string;
  time: string;
  notes: string;
};

function groupByDate(items: EventItem[]): { date: string; items: EventItem[] }[] {
  const groups: Record<string, EventItem[]> = {};
  items.forEach((e) => {
    (groups[e.date] ||= []).push(e);
  });
  return Object.keys(groups)
    .sort((a, b) => (a < b ? 1 : -1))
    .map((date) => ({ date, items: groups[date].sort((a, b) => (a.time < b.time ? 1 : -1)) }));
}

function formatDateLabel(date: string) {
  try {
    const d = new Date(date + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  } catch {
    return date;
  }
}

export default function TimelineScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const items = await api.listEvents();
      setEvents(items);
    } catch (e: any) {
      setError(e?.message || "Failed to load timeline");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const groups = useMemo(() => groupByDate(events), [events]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>Timeline</Text>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} testID="timeline-retry-button" style={styles.retry}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : events.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="book-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>Your timeline is waiting.</Text>
          <Text style={styles.emptyText}>Record what happened today.</Text>
          <Pressable onPress={() => router.push("/event/add")} style={styles.emptyCta} testID="timeline-empty-add-button">
            <Text style={styles.emptyCtaText}>Add event</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        >
          {groups.map((g) => (
            <View key={g.date} style={styles.group}>
              <Text style={styles.groupHeader}>{formatDateLabel(g.date)}</Text>
              <View style={styles.groupList}>
                {g.items.map((e) => (
                  <Pressable
                    key={e.id}
                    style={styles.row}
                    onPress={() => router.push(`/event/${e.id}`)}
                    testID={`timeline-event-${e.id}`}
                  >
                    <View style={styles.rowTime}>
                      <Text style={styles.time}>{e.time}</Text>
                    </View>
                    <View style={styles.dotColumn}>
                      <View style={styles.dot} />
                      <View style={styles.dotLine} />
                    </View>
                    <View style={styles.rowBody}>
                      <Text style={styles.rowType}>{e.type.toUpperCase()}</Text>
                      <Text style={styles.rowTitle} numberOfLines={1}>{e.title}</Text>
                      {e.notes ? <Text style={styles.rowNotes} numberOfLines={2}>{e.notes}</Text> : null}
                    </View>
                  </Pressable>
                ))}
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  scroll: { paddingBottom: spacing.xxxl * 2 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  retryText: { color: colors.onSurface },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600", textAlign: "center" },
  emptyText: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  group: { marginTop: spacing.lg },
  groupHeader: {
    fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600",
    paddingHorizontal: spacing.xl, paddingVertical: spacing.sm, backgroundColor: colors.surface,
  },
  groupList: { paddingHorizontal: spacing.xl },
  row: { flexDirection: "row", paddingVertical: spacing.md, gap: spacing.md },
  rowTime: { width: 52, paddingTop: 2 },
  time: { fontSize: 12, color: colors.onSurfaceTertiary },
  dotColumn: { width: 12, alignItems: "center", paddingTop: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary },
  dotLine: { flex: 1, width: 1, backgroundColor: colors.border, marginTop: 4 },
  rowBody: { flex: 1 },
  rowType: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1, marginBottom: 2 },
  rowTitle: { fontSize: 16, color: colors.onSurface, fontWeight: "500" },
  rowNotes: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
});
