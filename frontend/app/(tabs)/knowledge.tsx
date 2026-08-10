import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import HeaderAvatar from "@/src/components/HeaderAvatar";
type Goal = {
  id: string;
  title: string;
  domain_id: string;
  domain_name: string;
  notes: string;
  deadline: string;
  status: string;
  checkin_cadence: string;
  journey_type?: string;
  expected_outcomes_total: number;
  expected_outcomes_completed: number;
  completion_pct: number;
};

const STATUS_COLORS: Record<string, string> = {
  active: colors.brandPrimary,
  paused: colors.warning,
  completed: colors.success,
  abandoned: colors.onSurfaceTertiary,
};

const JOURNEY_LABEL: Record<string, string> = {
  professional_qualification: "Qualification",
  skill: "Skill",
  course: "Course",
  subject: "Subject",
  book: "Book",
  custom: "Custom",
};

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

function cadenceLabel(c: string): string {
  if (!c) return "";
  return c.charAt(0).toUpperCase() + c.slice(1);
}

export default function KnowledgeScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setError(null);
    try {
      const all = (await api.listGoals()) as Goal[];
      const knowledgeGoals = all
        .filter((g) => (g.domain_name || "").toLowerCase() === "knowledge")
        .sort((a, b) => (a.status === "active" ? -1 : 1) - (b.status === "active" ? -1 : 1));
      setGoals(knowledgeGoals);
    } catch (e: any) {
      setError(e?.message || "Could not load journeys");
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

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const nx = new Set(prev);
      if (nx.has(id)) nx.delete(id); else nx.add(id);
      return nx;
    });
  };

  const enterSelect = (id: string) => {
    setSelectMode(true);
    setSelected(new Set([id]));
  };

  const exitSelect = () => {
    setSelectMode(false);
    setSelected(new Set());
  };

  const startMerge = () => {
    if (selected.size < 2) return;
    router.push({ pathname: "/goals/merge", params: { ids: Array.from(selected).join(",") } });
    exitSelect();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="knowledge-screen">
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.title}>Knowledge</Text>
          <Text style={styles.subtitle}>
            {selectMode ? `${selected.size} selected` : "Your learning journeys"}
          </Text>
        </View>
        <View style={styles.headerActions}>
          {selectMode ? (
            <>
              <Pressable
                onPress={startMerge}
                disabled={selected.size < 2}
                style={[styles.mergeBtn, selected.size < 2 && { opacity: 0.5 }]}
                testID="knowledge-merge-btn"
                hitSlop={8}
              >
                <Ionicons name="git-merge-outline" size={16} color={colors.onBrandPrimary} />
                <Text style={styles.mergeBtnText}>Merge</Text>
              </Pressable>
              <Pressable onPress={exitSelect} testID="knowledge-exit-select" hitSlop={12}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </>
          ) : (
            <>
              <Pressable
                onPress={() => router.push("/goals/add?domain=Knowledge")}
                testID="knowledge-add-button"
                hitSlop={12}
                style={styles.addBtn}
              >
                <Ionicons name="add" size={22} color={colors.onSurface} />
              </Pressable>
              <HeaderAvatar />
            </>
          )}
        </View>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} style={styles.retry} testID="knowledge-retry">
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : goals.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="school-outline" size={44} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No journeys yet.</Text>
          <Text style={styles.emptyText}>What do you want to learn?</Text>
          <Pressable
            onPress={() => router.push("/goals/add?domain=Knowledge")}
            style={styles.emptyCta}
            testID="knowledge-empty-add-button"
          >
            <Text style={styles.emptyCtaText}>Start a journey</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        >
          {goals.map((g) => {
            const isSelected = selected.has(g.id);
            return (
              <Pressable
                key={g.id}
                onPress={() => (selectMode ? toggleSelect(g.id) : router.push(`/goals/${g.id}`))}
                onLongPress={() => enterSelect(g.id)}
                style={[styles.card, isSelected && styles.cardSelected]}
                testID={`journey-row-${g.id}`}
              >
                {selectMode ? (
                  <View style={styles.checkboxRow}>
                    <Ionicons
                      name={isSelected ? "checkbox" : "square-outline"}
                      size={18}
                      color={isSelected ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                    <Text style={styles.checkboxLabel}>{isSelected ? "Selected" : "Tap to select"}</Text>
                  </View>
                ) : null}
                <View style={styles.cardTop}>
                  <Text style={styles.tag}>
                    {(g.journey_type && JOURNEY_LABEL[g.journey_type]?.toUpperCase()) || "LEARNING JOURNEY"}
                  </Text>
                  <View style={styles.statusPill}>
                    <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[g.status] || colors.brandPrimary }]} />
                    <Text style={styles.statusText}>{g.status}</Text>
                  </View>
                </View>
                <Text style={styles.cardTitle} numberOfLines={2}>{g.title}</Text>
                {g.notes ? <Text style={styles.cardDesc} numberOfLines={2}>{g.notes}</Text> : null}
                <View style={styles.progressBarTrack}>
                  <View style={[styles.progressBarFill, { width: `${Math.min(g.completion_pct, 100)}%` }]} />
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaText}>{g.expected_outcomes_completed}/{g.expected_outcomes_total} outcomes</Text>
                  {g.checkin_cadence ? (
                    <>
                      <Text style={styles.metaDot}>·</Text>
                      <Ionicons name="repeat-outline" size={12} color={colors.onSurfaceSecondary} />
                      <Text style={styles.metaText}>{cadenceLabel(g.checkin_cadence)}</Text>
                    </>
                  ) : null}
                  {g.deadline ? (
                    <>
                      <Text style={styles.metaDot}>·</Text>
                      <Ionicons name="calendar-outline" size={12} color={colors.onSurfaceSecondary} />
                      <Text style={styles.metaText}>by {formatDate(g.deadline)}</Text>
                    </>
                  ) : null}
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  headerLeft: { flex: 1 },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  subtitle: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  addBtn: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
  },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl * 2, gap: spacing.md },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  retryText: { color: colors.onSurface },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600", textAlign: "center" },
  emptyText: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  cardSelected: { borderWidth: 2, borderColor: colors.brandPrimary },
  checkboxRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  checkboxLabel: { fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  mergeBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill,
  },
  mergeBtnText: { color: colors.onBrandPrimary, fontWeight: "600", fontSize: 13 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  tag: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  cardTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600", lineHeight: 24 },
  cardDesc: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.xs, lineHeight: 18 },
  progressBarTrack: { height: 4, backgroundColor: colors.surfaceTertiary, borderRadius: 2, marginTop: spacing.md, overflow: "hidden" },
  progressBarFill: { height: 4, backgroundColor: colors.brandPrimary },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.sm, flexWrap: "wrap" },
  metaDot: { color: colors.onSurfaceTertiary, marginHorizontal: 2 },
  metaText: { fontSize: 12, color: colors.onSurfaceSecondary },
});
