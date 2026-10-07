import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import {
  api,
  PlanningSpaceResponse,
  PlanningSpaceTarget,
} from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

let planningSpaceCache: PlanningSpaceResponse | null = null;

function requestErrorMessage(value: unknown): string {
  if (typeof value === "object" && value !== null && "message" in value) {
    const message = Reflect.get(value, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return "Could not load your planning space.";
}

function formatMinutes(minutes: number): string {
  if (!Number.isFinite(minutes)) {
    return "—";
  }
  const hours = Math.round((minutes / 60) * 10) / 10;
  return `${hours}h`;
}

export default function PlanningSpaceScreen() {
  const router = useRouter();
  const [data, setData] = useState<PlanningSpaceResponse | null>(
    planningSpaceCache,
  );
  const [loading, setLoading] = useState(planningSpaceCache === null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (mode: "focus" | "refresh") => {
    if (mode === "refresh") {
      setRefreshing(true);
    } else if (planningSpaceCache === null) {
      setLoading(true);
    }

    setError(null);

    try {
      const next = await api.getPlanningSpace();
      planningSpaceCache = next;
      setData(next);
    } catch (caught: unknown) {
      setError(requestErrorMessage(caught));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load("focus");
    }, [load]),
  );

  // Initial loading state — no cached or previously loaded data yet.
  if (data === null && loading) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.centerFill}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={styles.loadingText}>Bringing your plans together…</Text>
        </View>
      </SafeAreaView>
    );
  }

  // Initial error state — no cached data to display.
  if (data === null && error !== null) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.errorFill}>
          <Text style={styles.header}>Planning</Text>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable
            style={({ pressed }) => [styles.retryButton, pressed && { opacity: 0.85 }]}
            onPress={() => {
              void load("focus");
            }}
            testID="planning-space-retry"
          >
            <Text style={styles.retryButtonText}>Try again</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (data === null) {
    // Defensive — should not be reachable, but keeps the type system honest.
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.centerFill}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={styles.loadingText}>Bringing your plans together…</Text>
        </View>
      </SafeAreaView>
    );
  }

  const time = data.capacity.time;
  const money = data.capacity.money;
  const totals = data.portfolio_totals;
  const unscoped = data.unscoped_workload;

  const hasUnscopedWork =
    unscoped.open_task_count > 0 ||
    unscoped.overdue_task_count > 0 ||
    unscoped.due_this_week_task_count > 0;

  const currencyEntries = Object.entries(money.by_currency).sort(
    ([a], [b]) => (a < b ? -1 : a > b ? 1 : 0),
  );

  function openTarget(target: PlanningSpaceTarget): void {
    if (target.target_type === "goal") {
      router.push(`/goals/${target.target_id}`);
      return;
    }
    router.push(`/projects/${target.target_id}`);
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              void load("refresh");
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {/* Header */}
        <Text style={styles.header}>Planning</Text>
        <Text style={styles.subheader}>Week of {data.week_start_date}</Text>

        {/* Non-blocking refresh error */}
        {error !== null && (
          <View style={styles.inlineErrorBanner}>
            <Text style={styles.inlineErrorText}>{error}</Text>
            <Pressable
              style={({ pressed }) => [styles.inlineRetryButton, pressed && { opacity: 0.85 }]}
              onPress={() => {
                void load("focus");
              }}
              testID="planning-space-inline-retry"
            >
              <Text style={styles.inlineRetryButtonText}>Retry</Text>
            </Pressable>
          </View>
        )}

        {/* Time this week */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Time this week</Text>
          <Text style={styles.cardPrimary}>
            {formatMinutes(time.available_minutes)} uncommitted in your record
          </Text>
          <Text style={styles.cardSecondary}>
            {formatMinutes(time.committed_minutes)} recorded
          </Text>
          <View style={styles.breakdownList}>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Baseline</Text>
              <Text style={styles.breakdownValue}>
                {formatMinutes(time.baseline_committed_minutes)}
              </Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Reservations</Text>
              <Text style={styles.breakdownValue}>
                {formatMinutes(time.reserved_minutes)}
              </Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Overlap</Text>
              <Text style={styles.breakdownValue}>
                {formatMinutes(time.overlapping_minutes)}
              </Text>
            </View>
          </View>
          <Text style={styles.cardNote}>
            This is recorded availability, not guaranteed free time. Unrecorded sleep, travel, care and routines may still use it.
          </Text>
        </View>

        {/* Money available */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Money available</Text>
          {currencyEntries.length === 0 ? (
            <Text style={styles.cardEmpty}>No money position recorded.</Text>
          ) : (
            <View style={styles.currencyList}>
              {currencyEntries.map(([currency, row]) => (
                <View key={currency} style={styles.currencyBlock}>
                  <Text style={styles.cardPrimary}>
                    {currency} {row.available_unreserved} available
                  </Text>
                  <Text style={styles.cardSecondary}>
                    {currency} {row.reserved} reserved · {currency} {row.liquid_effective} effective liquid
                  </Text>
                </View>
              ))}
            </View>
          )}
          {money.pending_events.length > 0 && (
            <Text style={styles.cardNote}>
              This position is provisional. {money.pending_events.length} financial event(s) still need review.
            </Text>
          )}
        </View>

        {/* Portfolio */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Portfolio</Text>
          <View style={styles.breakdownList}>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Active goals</Text>
              <Text style={styles.breakdownValue}>{totals.active_goal_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Paused goals</Text>
              <Text style={styles.breakdownValue}>{totals.paused_goal_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Active projects</Text>
              <Text style={styles.breakdownValue}>{totals.active_project_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Paused projects</Text>
              <Text style={styles.breakdownValue}>{totals.paused_project_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Plans</Text>
              <Text style={styles.breakdownValue}>{totals.plan_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Open tasks</Text>
              <Text style={styles.breakdownValue}>{totals.open_task_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Overdue tasks</Text>
              <Text style={styles.breakdownValue}>{totals.overdue_task_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Due this week</Text>
              <Text style={styles.breakdownValue}>{totals.due_this_week_task_count}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={styles.breakdownLabel}>Required check-ins</Text>
              <Text style={styles.breakdownValue}>
                {totals.active_plan_required_checkin_count}
              </Text>
            </View>
          </View>
        </View>

        {/* Unscoped work */}
        {hasUnscopedWork && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Work not attached to an active goal or project</Text>
            <View style={styles.breakdownList}>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownLabel}>Open tasks</Text>
                <Text style={styles.breakdownValue}>{unscoped.open_task_count}</Text>
              </View>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownLabel}>Overdue tasks</Text>
                <Text style={styles.breakdownValue}>{unscoped.overdue_task_count}</Text>
              </View>
              <View style={styles.breakdownRow}>
                <Text style={styles.breakdownLabel}>Due this week</Text>
                <Text style={styles.breakdownValue}>{unscoped.due_this_week_task_count}</Text>
              </View>
            </View>
          </View>
        )}

        {/* Goals and projects */}
        <Text style={styles.sectionHeading}>Goals and projects</Text>
        {data.targets.length === 0 ? (
          <Text style={styles.cardEmpty}>No active or paused goals or projects.</Text>
        ) : (
          <View style={styles.targetList}>
            {data.targets.map((target) => {
              const kind = target.target_type === "goal" ? "Goal" : "Project";
              return (
                <Pressable
                  key={`${target.target_type}-${target.target_id}`}
                  style={({ pressed }) => [styles.targetCard, pressed && { opacity: 0.85 }]}
                  onPress={() => openTarget(target)}
                  testID={`planning-target-${target.target_type}-${target.target_id}`}
                >
                  <View style={styles.targetHeader}>
                    <Text style={styles.targetKind}>{kind}</Text>
                    <Ionicons
                      name="chevron-forward"
                      size={18}
                      color={colors.onSurfaceTertiary}
                    />
                  </View>
                  <Text style={styles.targetTitle} numberOfLines={2}>
                    {target.title}
                  </Text>
                  <View style={styles.targetMetaRow}>
                    <Text style={styles.targetMeta}>{target.status}</Text>
                    {target.deadline ? (
                      <Text style={styles.targetMeta}>{target.deadline}</Text>
                    ) : null}
                    {target.commitment_type === "exclusive" ? (
                      <Text style={styles.targetMeta}>Exclusive</Text>
                    ) : null}
                  </View>
                  <View style={styles.targetMetaRow}>
                    <Text style={styles.targetMeta}>
                      {target.plans.length} plan(s)
                    </Text>
                    <Text style={styles.targetMeta}>
                      {target.open_task_count} open
                    </Text>
                    <Text style={styles.targetMeta}>
                      {target.overdue_task_count} overdue
                    </Text>
                    <Text style={styles.targetMeta}>
                      {target.due_this_week_task_count} due this week
                    </Text>
                    <Text style={styles.targetMeta}>
                      {target.active_plan_required_checkin_count} required check-in(s)
                    </Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xxxl * 2,
  },

  centerFill: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.md,
  },
  loadingText: {
    fontSize: 14,
    color: colors.onSurfaceSecondary,
  },

  errorFill: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    gap: spacing.lg,
  },
  errorText: {
    fontSize: 14,
    color: colors.onSurfaceSecondary,
  },
  retryButton: {
    alignSelf: "flex-start",
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
  },
  retryButtonText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: "600",
  },

  header: {
    fontFamily: fonts.displayBold,
    fontSize: 36,
    color: colors.onSurface,
    fontWeight: "700",
  },
  subheader: {
    fontSize: 14,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.xs,
    marginBottom: spacing.xl,
  },

  inlineErrorBanner: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.error,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    marginBottom: spacing.lg,
  },
  inlineErrorText: {
    flex: 1,
    fontSize: 13,
    color: colors.error,
  },
  inlineRetryButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderStrong,
  },
  inlineRetryButtonText: {
    fontSize: 13,
    color: colors.onSurface,
    fontWeight: "600",
  },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    gap: spacing.sm,
  },
  cardTitle: {
    fontSize: 15,
    color: colors.onSurface,
    fontWeight: "600",
    marginBottom: spacing.xs,
  },
  cardPrimary: {
    fontSize: 16,
    color: colors.onSurface,
    fontWeight: "600",
  },
  cardSecondary: {
    fontSize: 13,
    color: colors.onSurfaceSecondary,
  },
  cardEmpty: {
    fontSize: 13,
    color: colors.onSurfaceSecondary,
  },
  cardNote: {
    fontSize: 12,
    color: colors.onSurfaceTertiary,
    marginTop: spacing.xs,
  },

  breakdownList: {
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  breakdownRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.xs,
    gap: spacing.md,
  },
  breakdownLabel: {
    flex: 1,
    fontSize: 13,
    color: colors.onSurfaceSecondary,
  },
  breakdownValue: {
    fontSize: 13,
    color: colors.onSurface,
    fontWeight: "600",
  },

  currencyList: {
    gap: spacing.md,
    marginTop: spacing.xs,
  },
  currencyBlock: {
    gap: spacing.xs,
  },

  sectionHeading: {
    fontSize: 15,
    color: colors.onSurface,
    fontWeight: "600",
    marginBottom: spacing.sm,
  },

  targetList: {
    gap: spacing.md,
  },
  targetCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  targetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  targetKind: {
    fontSize: 11,
    color: colors.brandPrimary,
    fontWeight: "700",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  targetTitle: {
    fontSize: 15,
    color: colors.onSurface,
    fontWeight: "600",
  },
  targetMetaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  targetMeta: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
  },
});
