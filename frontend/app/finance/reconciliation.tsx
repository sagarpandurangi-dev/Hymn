import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { api } from "@/src/lib/api";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";
import {
  beginResolution,
  financeReturnRoute,
  idleResolutionState,
  isResolutionBusy,
  reconciliationEmptyCopy,
  removeResolvedSuggestion,
  resolutionFailed,
  resolutionRefreshFailed,
  resolutionSaved,
  resolutionSucceeded,
  usefulError,
  type ReconciliationSuggestion,
  type ResolutionUiState,
} from "@/src/lib/reconciliation";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function ReconciliationScreen() {
  const router = useRouter();
  const inFlight = useRef(new Set<string>());
  const [items, setItems] = useState<ReconciliationSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [resolution, setResolution] = useState<ResolutionUiState>(
    idleResolutionState,
  );

  const loadPending = useCallback(async () => {
    const pending = await api.reconciliationSuggestions();
    setItems(pending);
    return pending;
  }, []);

  const initialLoad = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      await loadPending();
    } catch (error) {
      setLoadError(
        usefulError(error, "Could not load expenses awaiting reconciliation."),
      );
    } finally {
      setLoading(false);
    }
  }, [loadPending]);

  useEffect(() => {
    void initialLoad();
  }, [initialLoad]);

  const refreshAfterSaved = async () => {
    if (
      resolution.phase !== "saved_refresh_failed" &&
      resolution.phase !== "success"
    ) {
      return;
    }
    const { eventId, message } = resolution;
    setResolution({ phase: "saved_refreshing", eventId, message });
    try {
      await Promise.all([loadPending(), api.getFinanceDashboard()]);
      setResolution({ phase: "success", eventId, message });
    } catch (error) {
      setResolution({
        phase: "saved_refresh_failed",
        eventId,
        message,
        refreshError: usefulError(
          error,
          "Finance could not refresh. Your decision is still saved.",
        ),
      });
    }
  };

  const resolveUnplanned = async (item: ReconciliationSuggestion) => {
    const eventId = item.event.id;
    if (inFlight.current.has(eventId)) return;
    inFlight.current.add(eventId);
    setResolution(beginResolution(eventId));
    try {
      const result = await api.reconcileReject(eventId);
      // The backend has now committed the final state. Remove the card
      // immediately so a refresh failure cannot encourage another submission.
      setItems((current) => removeResolvedSuggestion(current, eventId));
      setResolution(resolutionSaved(result));
      try {
        const [pending] = await Promise.all([
          api.reconciliationSuggestions(),
          api.getFinanceDashboard(),
        ]);
        setItems(pending);
        setResolution(resolutionSucceeded(result));
      } catch (refreshError) {
        setResolution(
          resolutionRefreshFailed(
            result,
            usefulError(
              refreshError,
              "Finance could not refresh. Your decision is still saved.",
            ),
          ),
        );
      }
    } catch (error) {
      setResolution(
        resolutionFailed(
          eventId,
          usefulError(
            error,
            "Could not save this as an unplanned expense. Try again.",
          ),
        ),
      );
    } finally {
      inFlight.current.delete(eventId);
    }
  };

  const confirmMatch = async (
    item: ReconciliationSuggestion,
    commitmentId: string,
  ) => {
    const eventId = item.event.id;
    if (inFlight.current.has(eventId)) return;
    inFlight.current.add(eventId);
    setResolution(beginResolution(eventId));
    try {
      await api.reconcileConfirm(eventId, { commitment_id: commitmentId });
      setItems((current) => removeResolvedSuggestion(current, eventId));
      const message = "Expense matched to the planned commitment.";
      setResolution({ phase: "saved_refreshing", eventId, message });
      try {
        const [pending] = await Promise.all([
          api.reconciliationSuggestions(),
          api.getFinanceDashboard(),
        ]);
        setItems(pending);
        setResolution({ phase: "success", eventId, message });
      } catch (refreshError) {
        setResolution({
          phase: "saved_refresh_failed",
          eventId,
          message,
          refreshError: usefulError(
            refreshError,
            "Finance could not refresh. Your match is still saved.",
          ),
        });
      }
    } catch (error) {
      setResolution(
        resolutionFailed(
          eventId,
          usefulError(error, "Could not save this match. Try again."),
        ),
      );
    } finally {
      inFlight.current.delete(eventId);
    }
  };

  const anyBusy =
    resolution.phase === "submitting" ||
    resolution.phase === "saved_refreshing";
  const hasSavedResolution =
    resolution.phase === "success" ||
    resolution.phase === "saved_refresh_failed";
  const emptyCopy = reconciliationEmptyCopy(hasSavedResolution);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader
        title="Reconciliation"
        subtitle="Decide whether actual expenses match your plans"
      />

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={styles.helper}>Loading expenses…</Text>
        </View>
      ) : loadError ? (
        <View style={styles.center}>
          <Ionicons name="alert-circle-outline" size={30} color={colors.error} />
          <Text style={styles.emptyTitle}>Finance could not load</Text>
          <Text style={styles.errorText}>{loadError}</Text>
          <Pressable style={styles.primary} onPress={() => void initialLoad()}>
            <Text style={styles.primaryText}>Try again</Text>
          </Pressable>
          <Pressable
            style={styles.secondary}
            onPress={() => router.replace(financeReturnRoute)}
          >
            <Text style={styles.secondaryText}>Back to Finance</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {resolution.phase === "saved_refreshing" ? (
            <View style={styles.successCard} testID="recon-saved-refreshing">
              <ActivityIndicator color={colors.brandPrimary} />
              <View style={styles.flex}>
                <Text style={styles.successTitle}>Saved</Text>
                <Text style={styles.successText}>{resolution.message}</Text>
                <Text style={styles.helper}>Refreshing Finance totals…</Text>
              </View>
            </View>
          ) : null}

          {resolution.phase === "success" ? (
            <View style={styles.successCard} testID="recon-success">
              <Ionicons name="checkmark-circle" size={22} color={colors.success} />
              <View style={styles.flex}>
                <Text style={styles.successTitle}>Saved</Text>
                <Text style={styles.successText}>{resolution.message}</Text>
              </View>
              <Pressable
                onPress={() => router.replace(financeReturnRoute)}
                testID="recon-view-finance"
              >
                <Text style={styles.linkText}>View Finance</Text>
              </Pressable>
            </View>
          ) : null}

          {resolution.phase === "saved_refresh_failed" ? (
            <View style={styles.warningCard} testID="recon-partial-success">
              <Text style={styles.warningTitle}>Your decision was saved</Text>
              <Text style={styles.successText}>{resolution.message}</Text>
              <Text style={styles.errorText}>{resolution.refreshError}</Text>
              <View style={styles.actions}>
                <Pressable
                  style={styles.primary}
                  onPress={() => void refreshAfterSaved()}
                  testID="recon-refresh-after-save"
                >
                  <Text style={styles.primaryText}>Refresh Finance</Text>
                </Pressable>
                <Pressable
                  style={styles.secondary}
                  onPress={() => router.replace(financeReturnRoute)}
                >
                  <Text style={styles.secondaryText}>Back to Finance</Text>
                </Pressable>
              </View>
            </View>
          ) : null}

          {items.length === 0 ? (
            <View style={styles.emptyCard} testID="recon-empty">
              <Ionicons name="checkmark-done-circle-outline" size={34} color={colors.success} />
              <Text style={styles.emptyTitle}>{emptyCopy.title}</Text>
              <Text style={styles.helper}>{emptyCopy.body}</Text>
              <Pressable
                style={styles.primary}
                onPress={() => router.replace(financeReturnRoute)}
                testID="recon-back-to-finance"
              >
                <Text style={styles.primaryText}>Back to Finance</Text>
              </Pressable>
            </View>
          ) : null}

          {items.map((item) => {
            const itemBusy = isResolutionBusy(resolution, item.event.id);
            const itemFailed =
              resolution.phase === "failed" &&
              resolution.eventId === item.event.id;
            return (
              <View key={item.event.id} style={styles.card}>
                <Text style={styles.title}>
                  {item.event.description || "Recorded expense"}
                </Text>
                <Text style={styles.meta}>
                  {item.event.currency} {formatMoney(item.event.amount)} ·{" "}
                  {dateLabel(item.event.event_date)} · {item.event.source}
                </Text>

                {itemFailed ? (
                  <View style={styles.inlineError} testID={`recon-error-${item.event.id}`}>
                    <Text style={styles.errorText}>{resolution.message}</Text>
                    <Text style={styles.helper}>
                      Nothing new was recorded. You can safely retry.
                    </Text>
                  </View>
                ) : null}

                {item.single_strong_match ? (
                  <>
                    <Text style={styles.body}>
                      Possible match: {item.single_strong_match.commitment.title}
                    </Text>
                    <Text style={styles.body}>
                      Confirming will attach this existing actual expense to the
                      commitment. It will not create another transaction.
                    </Text>
                    <View style={styles.actions}>
                      <Pressable
                        style={[styles.primary, anyBusy && styles.disabled]}
                        disabled={anyBusy}
                        onPress={() =>
                          void confirmMatch(
                            item,
                            item.single_strong_match!.commitment.id,
                          )
                        }
                        testID={`recon-confirm-${item.event.id}`}
                      >
                        {itemBusy ? (
                          <ActivityIndicator color={colors.onBrandPrimary} />
                        ) : (
                          <Text style={styles.primaryText}>Confirm match</Text>
                        )}
                      </Pressable>
                      <Pressable
                        style={[styles.secondary, anyBusy && styles.disabled]}
                        disabled={anyBusy}
                        onPress={() => void resolveUnplanned(item)}
                        testID={`recon-reject-${item.event.id}`}
                      >
                        <Text style={styles.secondaryText}>Not this plan</Text>
                      </Pressable>
                    </View>
                  </>
                ) : item.matches.length > 0 ? (
                  <>
                    <Text style={styles.body}>
                      Hymn found possible planned commitments. Choose one, or
                      record this as unplanned.
                    </Text>
                    {item.matches.map((match) => (
                      <Pressable
                        key={match.commitment.id}
                        style={[styles.matchRow, anyBusy && styles.disabled]}
                        disabled={anyBusy}
                        onPress={() =>
                          void confirmMatch(item, match.commitment.id)
                        }
                        testID={`recon-pick-${item.event.id}-${match.commitment.id}`}
                      >
                        <View style={styles.flex}>
                          <Text style={styles.matchTitle}>
                            {match.commitment.title}
                          </Text>
                          <Text style={styles.matchMeta}>
                            {match.commitment.currency}{" "}
                            {formatMoney(match.commitment.amount)} · due{" "}
                            {dateLabel(match.commitment.due_date)}
                          </Text>
                        </View>
                      </Pressable>
                    ))}
                    <Pressable
                      style={[styles.secondary, anyBusy && styles.disabled]}
                      disabled={anyBusy}
                      onPress={() => void resolveUnplanned(item)}
                      testID={`recon-none-${item.event.id}`}
                    >
                      {itemBusy ? (
                        <ActivityIndicator color={colors.onSurface} />
                      ) : (
                        <Text style={styles.secondaryText}>
                          None — record as unplanned
                        </Text>
                      )}
                    </Pressable>
                  </>
                ) : (
                  <>
                    <Text style={styles.body}>
                      This does not match a planned commitment. Record it as an
                      unplanned actual expense?
                    </Text>
                    <Text style={styles.helper}>
                      Hymn will not change an account balance because no paying
                      account was selected.
                    </Text>
                    <Pressable
                      style={[styles.secondary, anyBusy && styles.disabled]}
                      disabled={anyBusy}
                      onPress={() => void resolveUnplanned(item)}
                      testID={`recon-unplanned-${item.event.id}`}
                    >
                      {itemBusy ? (
                        <View style={styles.loadingRow}>
                          <ActivityIndicator color={colors.onSurface} />
                          <Text style={styles.secondaryText}>Saving…</Text>
                        </View>
                      ) : (
                        <Text style={styles.secondaryText}>Yes, unplanned</Text>
                      )}
                    </Pressable>
                  </>
                )}
              </View>
            );
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  scroll: {
    padding: spacing.xl,
    gap: spacing.md,
    paddingBottom: spacing.xxxl,
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.xl,
  },
  card: {
    padding: spacing.lg,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    gap: spacing.sm,
  },
  title: {
    fontFamily: fonts.displayBold,
    fontSize: 16,
    color: colors.onSurface,
    fontWeight: "700",
  },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary },
  body: {
    fontSize: 13,
    color: colors.onSurface,
    marginTop: spacing.xs,
    lineHeight: 19,
  },
  helper: {
    fontSize: 13,
    color: colors.onSurfaceSecondary,
    lineHeight: 19,
    textAlign: "center",
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  primary: {
    minHeight: 44,
    backgroundColor: colors.onSurface,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    flex: 1,
  },
  primaryText: {
    color: colors.onSurfaceInverse,
    fontSize: 13,
    fontWeight: "700",
  },
  secondary: {
    minHeight: 44,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    flex: 1,
    marginTop: spacing.sm,
  },
  secondaryText: {
    color: colors.onSurface,
    fontSize: 13,
    fontWeight: "600",
  },
  disabled: { opacity: 0.5 },
  loadingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  matchRow: {
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  matchTitle: {
    fontSize: 13,
    color: colors.onSurface,
    fontWeight: "600",
  },
  matchMeta: {
    fontSize: 11,
    color: colors.onSurfaceSecondary,
    marginTop: 2,
  },
  successCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
  },
  successTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: colors.onSurface,
  },
  successText: {
    fontSize: 13,
    color: colors.onSurfaceSecondary,
    lineHeight: 19,
    marginTop: 2,
  },
  linkText: {
    color: colors.brandPrimary,
    fontSize: 13,
    fontWeight: "700",
  },
  warningCard: {
    padding: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: "#F5E6C7",
  },
  warningTitle: {
    color: colors.onSurface,
    fontSize: 14,
    fontWeight: "700",
  },
  inlineError: {
    backgroundColor: "#FDECEA",
    borderRadius: radius.sm,
    padding: spacing.md,
  },
  errorText: {
    color: colors.error,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
  },
  emptyCard: {
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.xl,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
  },
  emptyTitle: {
    fontFamily: fonts.displayBold,
    color: colors.onSurface,
    fontSize: 18,
    fontWeight: "700",
    textAlign: "center",
  },
});
