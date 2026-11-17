/**
 * Finance tab — Fold-inspired dashboard.
 *
 * Every KPI, total and chart is drillable. The screen only fetches a
 * single ``GET /api/screens/finance`` (plus reconciliation suggestions) and renders what the backend
 * returned — no math on the client. This is a pure UI refresh; data
 * primitives and routes are unchanged.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, PlannedItem } from "@/src/lib/api";
import PlannedItemForm from "@/src/components/finance/PlannedItemForm";
import PlannedRow from "@/src/components/finance/PlannedRow";
import HeaderAvatar from "@/src/components/HeaderAvatar";
import {
  FoldAmount,
  FoldBanner,
  FoldCard,
  FoldPill,
  FoldRow,
  FoldSectionHeader,
  foldPageStyle,
} from "@/src/components/finance/foldUi";
import { financeColors, financeSpace, financeType } from "@/src/lib/finance/theme";
import {
  currentMonthIso,
  dateLabel,
  formatMoney,
  monthLabel,
} from "@/src/lib/finance/format";

export default function FinanceScreen() {
  const router = useRouter();
  const [dash, setDash] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planned, setPlanned] = useState<PlannedItem[]>([]);
  const [plannedFormOpen, setPlannedFormOpen] = useState(false);
  const [plannedEditing, setPlannedEditing] = useState<PlannedItem | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [screen, recon] = await Promise.all([
        api.getFinanceScreen(),
        api.reconciliationSuggestions().catch(() => []),
      ]);
      setDash({ ...screen.dashboard, _recon_count: (recon || []).length });
      setPlanned(Array.isArray(screen.planned_upcoming) ? screen.planned_upcoming : []);
    } catch (e: any) {
      setError(e?.message || "Could not load Finance");
    }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  // Refresh quietly when coming back from Planned money, Statements, etc.
  const firstFocus = useRef(true);
  useFocusEffect(useCallback(() => {
    if (firstFocus.current) { firstFocus.current = false; return; }
    load();
  }, [load]));

  const retryInitialLoad = useCallback(async () => {
    setLoading(true);
    await load();
    setLoading(false);
  }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  if (loading) {
    return (
      <SafeAreaView style={foldPageStyle} edges={["top"]} testID="finance-screen">
        <ScreenHeader />
        <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} />
      </SafeAreaView>
    );
  }

  if (!dash && error) {
    return (
      <SafeAreaView style={foldPageStyle} edges={["top"]} testID="finance-screen">
        <ScreenHeader />
        <View style={styles.loadFailureWrap} testID="finance-load-error">
          <FoldCard style={styles.loadFailureCard}>
            <Ionicons
              name="cloud-offline-outline"
              size={32}
              color={financeColors.inkFaint}
            />
            <Text style={styles.loadFailureTitle}>
              Finance couldn’t load
            </Text>
            <Text style={styles.loadFailureBody}>
              Your financial data was not changed. Try loading Finance again.
            </Text>
            <Text style={styles.loadFailureDetail}>
              {error}
            </Text>
            <Pressable
              style={styles.loadFailureButton}
              onPress={retryInitialLoad}
              testID="finance-retry"
            >
              <Text style={styles.loadFailureButtonText}>
                Try again
              </Text>
            </Pressable>
          </FoldCard>
        </View>
      </SafeAreaView>
    );
  }

  const position = dash?.position?.currencies || [];
  const monthlyWindows: any[] = dash?.monthly_windows || [];
  // The server already returns the next 6 planned items, soonest first.
  const upcomingPlanned = planned;
  const plannedCurrency = planned[0]?.currency || position[0]?.currency || "INR";
  const reserved: any[] = dash?.reserved?.by_currency || dash?.reserved || [];
  const liquidity: any[] = dash?.available_liquidity?.by_currency || dash?.available_liquidity || [];
  const dueForReview: any[] = dash?.commitments_due_for_review || [];
  const recentEvents: any[] = dash?.recent_events || [];
  const multiCurrency = dash?.position?.multi_currency;

  return (
    <SafeAreaView style={foldPageStyle} edges={["top"]} testID="finance-screen">
      <ScreenHeader />
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={financeColors.inkMuted} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {dash && position.length === 0 ? (
          <EmptyState onOpenPortfolio={() => router.push("/portfolio")} />
        ) : null}

        {multiCurrency ? (
          <Text style={styles.fxNotice} testID="finance-fx-notice">{dash?.position?.notice}</Text>
        ) : null}

        {dueForReview.length > 0 && (
          <FoldBanner
            testID="finance-review-banner"
            icon="alarm-outline"
            tone="warn"
            text={`${dueForReview.length} commitment${dueForReview.length === 1 ? "" : "s"} due for review`}
            action={{ label: "Review", testID: "finance-open-reviews", onPress: () => router.push("/finance/reviews") }}
          />
        )}

        {dash?._recon_count > 0 && (
          <FoldBanner
            testID="finance-recon-banner"
            icon="git-compare-outline"
            tone="info"
            text={`${dash._recon_count} event${dash._recon_count === 1 ? "" : "s"} awaiting reconciliation`}
            action={{ label: "Reconcile", testID: "finance-open-recon", onPress: () => router.push("/finance/reconciliation") }}
          />
        )}

        {/* ============================================================
           1. Current Financial Position — hero net worth per currency
        ============================================================ */}
        {position.map((cur: any) => (
          <View key={`pos-${cur.currency}`} style={styles.blockGap} testID={`finance-position-${cur.currency}`}>
            <FoldSectionHeader label="Position" hint={cur.currency} />
            <FoldCard>
              <Pressable
                style={styles.heroPress}
                onPress={() => router.push(`/finance/position/net-worth?currency=${cur.currency}`)}
                testID={`kpi-net-worth-${cur.currency}`}
              >
                <Text style={styles.heroLabel}>Net worth</Text>
                <FoldAmount currency={cur.currency} value={formatMoney(cur.net_worth)} size="xl" />
              </Pressable>
              <FoldRow
                label="Total assets"
                right={<FoldAmount currency={cur.currency} value={formatMoney(cur.total_assets)} />}
                onPress={() => router.push(`/finance/position/assets?currency=${cur.currency}`)}
                chevron
                testID={`kpi-total-assets-${cur.currency}`}
              />
              <FoldRow
                label="Total liabilities"
                right={<FoldAmount currency={cur.currency} value={formatMoney(cur.total_liabilities)} />}
                onPress={() => router.push(`/finance/position/liabilities?currency=${cur.currency}`)}
                chevron
                testID={`kpi-total-liabilities-${cur.currency}`}
              />
            </FoldCard>

            <FoldCard style={{ marginTop: financeSpace.md }}>
              <FoldRow
                first
                label="Liquid"
                meta="Cash & instantly available balances"
                right={<FoldAmount currency={cur.currency} value={formatMoney(cur.liquid_assets)} />}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=liquid`)}
                chevron
                testID={`kpi-liquid-${cur.currency}`}
              />
              <FoldRow
                label="Semi-liquid"
                meta="Days to weeks to convert"
                right={<FoldAmount currency={cur.currency} value={formatMoney(cur.semi_liquid_assets)} />}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=semi_liquid`)}
                chevron
                testID={`kpi-semi-liquid-${cur.currency}`}
              />
              <FoldRow
                label="Illiquid"
                meta="Real estate, private holdings"
                right={<FoldAmount currency={cur.currency} value={formatMoney(cur.illiquid_assets)} />}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=illiquid`)}
                chevron
                testID={`kpi-illiquid-${cur.currency}`}
              />
            </FoldCard>
          </View>
        ))}

        {/* ============================================================
           2. Monthly Commitments — this month per currency
        ============================================================ */}
        {monthlyWindows.map((w: any) => {
          const cm = w.months?.[0];
          if (!cm) return null;
          return (
            <View key={`mm-${w.currency}`} style={styles.blockGap} testID={`finance-monthly-${w.currency}`}>
              <FoldSectionHeader
                label="This month"
                hint={`${w.currency} · ${monthLabel(cm.month)}`}
                action={{ label: "Browse", onPress: () => router.push(`/finance/monthly?currency=${w.currency}`) }}
              />
              <FoldCard>
                <FoldRow first label="Recurring income" right={<FoldAmount currency={w.currency} value={formatMoney(cm.recurring_income)} tone="positive" />} onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=income`)} chevron />
                <FoldRow label="Recurring expenses" right={<FoldAmount currency={w.currency} value={formatMoney(cm.recurring_expenses)} />} onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=expense`)} chevron />
                <FoldRow label="Debt payments" right={<FoldAmount currency={w.currency} value={formatMoney(cm.debt_payments)} />} onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=debt_payment`)} chevron />
                <FoldRow label="Savings" right={<FoldAmount currency={w.currency} value={formatMoney(cm.savings)} />} onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=saving`)} chevron />
                <FoldRow label="Investments" right={<FoldAmount currency={w.currency} value={formatMoney(cm.investments)} />} onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=investment`)} chevron />
                <View style={styles.freeCashBar}>
                  <Text style={styles.freeCashLabel}>Free cash</Text>
                  <FoldAmount currency={w.currency} value={formatMoney(cm.monthly_free_cash)} size="lg" tone={Number(cm.monthly_free_cash) < 0 ? "negative" : "positive"} />
                </View>
              </FoldCard>
            </View>
          );
        })}

        {/* ============================================================
           3. Planned money — next items + quick add
        ============================================================ */}
        <View style={styles.blockGap} testID="finance-planned">
          <FoldSectionHeader
            label="Planned money"
            action={{ label: "+ New", testID: "finance-planned-new", onPress: () => { setPlannedEditing(null); setPlannedFormOpen(true); } }}
          />
          {liquidity.length > 0 ? (
            <FoldCard testID="finance-available-money">
              {liquidity.map((l: any, idx: number) => {
                const setAside = l.reserved ?? l.reserved_total ?? reserved.find((r: any) => r.currency === l.currency)?.reserved_total;
                return (
                  <View key={`liq-${l.currency}`}>
                    <FoldRow
                      first={idx === 0}
                      label={`Available to spend (${l.currency})`}
                      meta="Liquid minus money set aside"
                      right={<FoldAmount currency={l.currency} value={formatMoney(l.available_unreserved)} size="md" tone="positive" />}
                      testID={`available-${l.currency}`}
                    />
                    {setAside != null ? (
                      <FoldRow
                        label={`Set aside (${l.currency})`}
                        right={<FoldAmount currency={l.currency} value={formatMoney(String(setAside))} />}
                        testID={`set-aside-${l.currency}`}
                      />
                    ) : null}
                    {l.pending_account_events && l.pending_account_events.length > 0 ? (
                      <FoldRow
                        label={`Pending account (${l.currency})`}
                        meta={`${l.pending_account_events.length} spend${l.pending_account_events.length === 1 ? "" : "s"} waiting for an account`}
                        right={<FoldPill label="Assign" tone="warn" size="xs" />}
                        onPress={() => router.push(`/finance/events`)}
                        chevron
                        testID={`pending-account-${l.currency}`}
                      />
                    ) : null}
                  </View>
                );
              })}
            </FoldCard>
          ) : null}
          <FoldCard>
            {upcomingPlanned.length === 0 ? (
              <View style={styles.emptyRow}>
                <Text style={styles.emptyRowText}>Nothing planned yet.</Text>
              </View>
            ) : (
              upcomingPlanned.map((it, idx) => (
                <PlannedRow key={it.id} item={it} first={idx === 0} onPress={() => { setPlannedEditing(it); setPlannedFormOpen(true); }} />
              ))
            )}
            <Pressable onPress={() => router.push("/finance/planned")} style={styles.moreRow} testID="finance-planned-see-all">
              <Text style={styles.moreText}>See all</Text>
              <Ionicons name="chevron-forward" size={14} color={financeColors.accent} />
            </Pressable>
          </FoldCard>
        </View>

        {/* ============================================================
           4. Twelve-month forecast — from the dashboard's forecast block
              (same server calculation as the full forecast screen)
        ============================================================ */}
        {(dash?.forecast?.by_currency || []).map((f: any) => {
          const months: any[] = (f.months || []).slice(0, 4);
          if (months.length === 0) return null;
          return (
            <View key={`fc-${f.currency}`} style={styles.blockGap} testID={`finance-forecast-${f.currency}`}>
              <FoldSectionHeader
                label="Twelve-month forecast"
                hint={`${f.currency} · confidence ${f.confidence}`}
                action={{ label: "Full forecast", onPress: () => router.push(`/finance/forecast?currency=${f.currency}`) }}
              />
              <FoldCard>
                <View style={styles.subHead}>
                  <Text style={styles.subHeadText}>Liquidity — can obligations be met?</Text>
                </View>
                {months.map((m: any, idx: number) => (
                  <FoldRow
                    key={`liq-${m.month}`}
                    first={idx === 0}
                    label={monthLabel(m.month)}
                    meta={`Income ${formatMoney(m.recurring_income)} · outflow ${formatMoney(m.recurring_outflows)} · reserved ${formatMoney(m.reserved_commitments_amount)}`}
                    right={<FoldAmount currency={f.currency} value={formatMoney(m.projected_liquid_end_of_month)} tone={m.shortfall ? "negative" : "ink"} />}
                    onPress={() => router.push(`/finance/forecast-month?currency=${f.currency}&month=${m.month}`)}
                    chevron
                    testID={`finance-forecast-liq-${f.currency}-${m.month}`}
                  />
                ))}
              </FoldCard>
              {months.some((m: any) => m.projected_net_worth_end_of_month != null) ? (
                <FoldCard style={{ marginTop: financeSpace.md }}>
                  <View style={styles.subHead}>
                    <Text style={styles.subHeadText}>Net worth — how does wealth change?</Text>
                  </View>
                  {months.map((m: any, idx: number) => (
                    <FoldRow
                      key={`nw-${m.month}`}
                      first={idx === 0}
                      label={monthLabel(m.month)}
                      right={<FoldAmount currency={f.currency} value={formatMoney(m.projected_net_worth_end_of_month)} />}
                    />
                  ))}
                </FoldCard>
              ) : null}
              {typeof f.basis === "string" && f.basis.trim() ? (
                <Text style={styles.basisNote} testID={`finance-forecast-basis-${f.currency}`}>{f.basis}</Text>
              ) : null}
            </View>
          );
        })}

        {/* Documents — statements and money book */}
        <View style={styles.blockGap}>
          <FoldSectionHeader label="Documents" />
          <FoldCard>
            <FoldRow
              first
              label="Statements"
              meta="Upload bank statements and check they add up."
              onPress={() => router.push(`/finance/statements`)}
              chevron
              testID="finance-statements"
            />
            <FoldRow
              label="Money book"
              meta="Review and approve setting up your money book."
              onPress={() => router.push(`/finance/money-book`)}
              chevron
              testID="finance-money-book"
            />
          </FoldCard>
        </View>

        {/* ============================================================
           6. Recent actual events
        ============================================================ */}
        <View style={styles.blockGap} testID="finance-events">
          <FoldSectionHeader
            label="Recent activity"
            action={{ label: "All events", onPress: () => router.push("/finance/events") }}
          />
          {recentEvents.length === 0 ? (
            <FoldCard>
              <View style={styles.emptyRow}>
                <Text style={styles.emptyRowText}>Check-ins with money spent, imports and manual events appear here.</Text>
              </View>
            </FoldCard>
          ) : (
            <FoldCard>
              {recentEvents.slice(0, 8).map((e: any, idx: number) => (
                <FoldRow
                  key={e.id}
                  first={idx === 0}
                  label={e.description || "(no description)"}
                  meta={`${dateLabel(e.event_date)} · ${e.source}`}
                  right={
                    <FoldAmount
                      currency={e.currency}
                      value={formatMoney(e.amount)}
                      sign={e.direction === "outflow" ? "-" : "+"}
                      tone={e.direction === "inflow" ? "positive" : "ink"}
                    />
                  }
                  onPress={() => router.push(`/finance/events/${e.id}`)}
                  chevron
                  testID={`event-${e.id}`}
                />
              ))}
            </FoldCard>
          )}
        </View>

        <Text style={styles.footerNote}>
          Generated {dash?.generated_at?.slice(0, 16).replace("T", " ")} UTC · month {currentMonthIso()}
        </Text>
      </ScrollView>
      <PlannedItemForm
        visible={plannedFormOpen}
        item={plannedEditing}
        defaultCurrency={plannedCurrency}
        onClose={() => { setPlannedFormOpen(false); setPlannedEditing(null); }}
        onSaved={async () => { setPlannedFormOpen(false); setPlannedEditing(null); await load(); }}
      />
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Screen header — big Fold-style display title
// ---------------------------------------------------------------------------
function ScreenHeader() {
  return (
    <View style={styles.header}>
      <View>
        <Text style={styles.eyebrow}>FINANCE</Text>
        <Text style={styles.title}>Overview</Text>
      </View>
      <HeaderAvatar />
    </View>
  );
}

function EmptyState({ onOpenPortfolio }: { onOpenPortfolio: () => void }) {
  return (
    <FoldCard style={{ padding: financeSpace.xl, alignItems: "center", gap: financeSpace.md }}>
      <Ionicons name="wallet-outline" size={32} color={financeColors.inkFaint} />
      <Text style={styles.emptyTitle}>Set up your portfolio first</Text>
      <Text style={styles.emptyBody}>Finance mirrors your Portfolio in real time. Add accounts and monthly commitments in Portfolio to see this dashboard populate.</Text>
      <Pressable style={styles.emptyCta} onPress={onOpenPortfolio} testID="finance-open-portfolio">
        <Text style={styles.emptyCtaText}>Open portfolio</Text>
      </Pressable>
    </FoldCard>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    paddingHorizontal: financeSpace.xl,
    paddingTop: financeSpace.sm,
    paddingBottom: financeSpace.lg,
  },
  eyebrow: {
    ...financeType.sectionLabel,
    marginBottom: 4,
  } as any,
  title: {
    ...financeType.screenTitle,
    fontSize: 34,
  } as any,
  scroll: {
    paddingHorizontal: financeSpace.xl,
    paddingBottom: financeSpace.xxxl * 2,
    gap: financeSpace.lg,
  },
  error: { color: financeColors.danger, fontSize: 13 },
  blockGap: { gap: 0 },
  heroPress: {
    paddingHorizontal: financeSpace.lg,
    paddingTop: financeSpace.lg,
    paddingBottom: financeSpace.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: financeColors.divider,
  },
  heroLabel: {
    ...financeType.sectionLabel,
    marginBottom: 6,
  } as any,
  freeCashBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: financeSpace.lg,
    paddingVertical: financeSpace.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: financeColors.divider,
    backgroundColor: "#FAFAF5",
  },
  freeCashLabel: {
    ...financeType.sectionLabel,
    color: financeColors.ink,
  } as any,
  moreRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: financeSpace.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: financeColors.divider,
  },
  moreText: { color: financeColors.accent, fontSize: 12.5, fontWeight: "700", letterSpacing: 0.3 },
  subHead: { paddingHorizontal: financeSpace.lg, paddingTop: financeSpace.md, paddingBottom: 6 },
  subHeadText: { fontSize: 11.5, color: financeColors.inkMuted, fontStyle: "italic" },
  basisNote: { fontSize: 12, color: financeColors.inkMuted, lineHeight: 17, marginTop: financeSpace.sm },
  emptyRow: { padding: financeSpace.lg, paddingVertical: financeSpace.xl },
  emptyRowText: { fontSize: 13, color: financeColors.inkMuted, lineHeight: 19 },
  fxNotice: {
    fontSize: 11.5,
    color: financeColors.inkMuted,
    fontStyle: "italic",
    lineHeight: 16,
    paddingHorizontal: 2,
  },
  footerNote: {
    fontSize: 10.5,
    color: financeColors.inkFaint,
    textAlign: "center",
    marginTop: financeSpace.md,
    letterSpacing: 0.4,
  },
  emptyTitle: {
    ...financeType.screenTitle,
    fontSize: 18,
    textAlign: "center",
  } as any,
  emptyBody: {
    fontSize: 13,
    color: financeColors.inkMuted,
    textAlign: "center",
    lineHeight: 19,
  },
  emptyCta: {
    backgroundColor: financeColors.ink,
    paddingHorizontal: financeSpace.xl,
    paddingVertical: financeSpace.md,
    borderRadius: 999,
    marginTop: 4,
  },
  emptyCtaText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  loadFailureWrap: {
    paddingHorizontal: financeSpace.xl,
    paddingTop: financeSpace.xl,
  },
  loadFailureCard: {
    padding: financeSpace.xl,
    alignItems: "center",
    gap: financeSpace.md,
  },
  loadFailureTitle: {
    ...financeType.screenTitle,
    fontSize: 20,
    textAlign: "center",
  },
  loadFailureBody: {
    color: financeColors.inkMuted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
  },
  loadFailureDetail: {
    color: financeColors.danger,
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center",
  },
  loadFailureButton: {
    backgroundColor: financeColors.ink,
    paddingHorizontal: financeSpace.xl,
    paddingVertical: financeSpace.md,
    borderRadius: 999,
    marginTop: 4,
  },
  loadFailureButtonText: {
    color: financeColors.card,
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
});
