import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Keyboard,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import HeaderAvatar from "@/src/components/HeaderAvatar";

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

/**
 * Render text with the matched substring emphasised. Match is case-insensitive
 * and treats `needle` as a literal (regex meta-characters are escaped). If no
 * match is found the plain text is returned as a single Text node.
 */
function highlight(text: string, needle: string, baseStyle: any, hitStyle: any, numberOfLines?: number) {
  if (!text) return <Text style={baseStyle} numberOfLines={numberOfLines}>{text}</Text>;
  const n = (needle || "").trim();
  if (!n) return <Text style={baseStyle} numberOfLines={numberOfLines}>{text}</Text>;
  const escaped = n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(escaped, "ig");
  const parts: { txt: string; hit: boolean }[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ txt: text.slice(last, m.index), hit: false });
    parts.push({ txt: m[0], hit: true });
    last = m.index + m[0].length;
    if (m.index === re.lastIndex) re.lastIndex++;  // avoid zero-length infinite loop
  }
  if (last < text.length) parts.push({ txt: text.slice(last), hit: false });
  if (parts.length === 0) return <Text style={baseStyle} numberOfLines={numberOfLines}>{text}</Text>;
  return (
    <Text style={baseStyle} numberOfLines={numberOfLines}>
      {parts.map((p, i) => (
        <Text key={i} style={p.hit ? hitStyle : undefined}>{p.txt}</Text>
      ))}
    </Text>
  );
}

export default function TimelineScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Search state — `query` is the raw text input; `debounced` is what we
  // actually send to the server. This decouples UI responsiveness from
  // network round-trips.
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The server-side filter is already user-scoped (user_id filter is applied
  // before any $regex match), so a search request will never surface another
  // user's check-ins even if the query string is wide open.
  const load = useCallback(async (opts?: { silent?: boolean; term?: string }) => {
    if (!opts?.silent) setError(null);
    const currentTerm = opts?.term !== undefined ? opts.term : debounced;
    try {
      if (currentTerm) setSearching(true);
      const items = await api.listCheckins(currentTerm ? { q: currentTerm } : undefined);
      setEvents(items);
    } catch (e: any) {
      if (!opts?.silent) setError(e?.message || "Failed to load timeline");
    } finally {
      setLoading(false);
      setSearching(false);
    }
  }, [debounced]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Debounce keystrokes -> `debounced`; whenever that settles, fire a fresh
  // search. 250ms is short enough to feel instant but long enough that a
  // typical typing burst produces one request instead of one per keystroke.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebounced(query.trim()), 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  useEffect(() => {
    // On first render `debounced` starts as "" — that matches the initial
    // useFocusEffect load and just re-fetches the full list. Subsequent
    // changes correspond to real user typing.
    load({ silent: true, term: debounced });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const groups = useMemo(() => groupByDate(events), [events]);
  const resultCount = events.length;
  const isSearchActive = !!debounced;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.title}>Timeline</Text>
        <HeaderAvatar />
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={16} color={colors.onSurfaceTertiary} />
        <TextInput
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="Search your check-ins"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCorrect={false}
          autoCapitalize="none"
          returnKeyType="search"
          onSubmitEditing={() => Keyboard.dismiss()}
          testID="timeline-search-input"
        />
        {query.length > 0 ? (
          <Pressable onPress={() => setQuery("")} hitSlop={12} testID="timeline-search-clear">
            <Ionicons name="close-circle" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : searching ? (
          <ActivityIndicator size="small" color={colors.brandPrimary} />
        ) : null}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={() => load()} testID="timeline-retry-button" style={styles.retry}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : events.length === 0 ? (
        isSearchActive ? (
          <View style={styles.emptyWrap} testID="timeline-search-empty">
            <Ionicons name="search-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>No matches for &ldquo;{debounced}&rdquo;.</Text>
            <Text style={styles.emptyText}>Try a different word — search covers titles and notes.</Text>
          </View>
        ) : (
          <View style={styles.emptyWrap}>
            <Ionicons name="book-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>Your timeline is waiting.</Text>
            <Text style={styles.emptyText}>Record what happened today.</Text>
            <Pressable onPress={() => router.push("/checkin/life")} style={styles.emptyCta} testID="timeline-empty-add-button">
              <Text style={styles.emptyCtaText}>Add check-in</Text>
            </Pressable>
          </View>
        )
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
          keyboardShouldPersistTaps="handled"
        >
          {isSearchActive && (
            <Text style={styles.resultCount} testID="timeline-result-count">
              {resultCount} result{resultCount === 1 ? "" : "s"} for &ldquo;{debounced}&rdquo;
            </Text>
          )}
          {groups.map((g) => (
            <View key={g.date} style={styles.group}>
              <Text style={styles.groupHeader}>{formatDateLabel(g.date)}</Text>
              <View style={styles.groupList}>
                {g.items.map((e) => (
                  <Pressable
                    key={e.id}
                    style={styles.row}
                    onPress={() => router.push(`/checkin/${e.id}`)}
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
                      {highlight(e.title, debounced, styles.rowTitle, styles.hit, 1)}
                      {e.notes ? highlight(e.notes, debounced, styles.rowNotes, styles.hit, 2) : null}
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
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.onSurface, paddingVertical: 0 },
  resultCount: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
  },
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
  // Highlighted matched substring — kept intentionally subtle so it reads
  // as emphasis, not as a colour explosion.
  hit: { backgroundColor: colors.brandTertiary, color: colors.onSurface, fontWeight: "700" },
});
