/**
 * Finance tab — Fold-inspired dashboard.
 *
 * Every KPI, total and chart is drillable. The screen only fetches a
 * single ``GET /api/finance/dashboard`` and renders what the backend
 * returned — no math on the client. This is a pure UI refresh; data
 * primitives and routes are unchanged.
 */
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
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

// ---------------------------------------------------------------------------
// State → pill tone mapping (muted Fold-style, replaces saturated stateColor).
// ---------------------------------------------------------------------------
const STATE_TONE: Record<string, "neutral" | "info" | "ok" | "err" | "warn"> = {
  draft: "neutral",
  reserved: "info",
  completed: "ok",
  cancelled: "neutral",
  expired: "err",
};

const STATE_LABEL: Record<string, string> = {
  draft: "Draft",
  reserved: "Reserved",
  completed: "Completed",
  cancelled: "Cancelled",
  expired: "Expired",
};

export default function FinanceScreen() {
  const router = useRouter();
  const [dash, setDash] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [d, twin, recon] = await Promise.all([
        api.getFinanceDashboard(),
        api.getTwinForecasts().catch(() => null),
        api.reconciliationSuggestions().catch(() => []),
      ]);
      setDash({ ...d, _twin: twin, _recon_count: (recon || []).length });
    } catch (e: any) {
      setError(e?.message || "Could not load Finance");
    }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  if (loading) {
    return (
      <SafeAreaView style={foldPageStyle} edges={["top"]} testID="finance-screen">
        <ScreenHeader />
        <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} />
      </SafeAreaView>
    );
  }

  const position = dash?.position?.currencies || [];
  const monthlyWindows: any[] = dash?.monthly_windows || [];
  const reserved: any[] = dash?.reserved?.by_currency || dash?.reserved || [];
  const liquidity: any[] = dash?.available_liquidity?.by_currency || dash?.available_liquidity || [];
  const activeCommitments: any[] = dash?.active_commitments || [];
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

        {position.length === 0 && <EmptyState onOpenPortfolio={() => router.push("/portfolio")} />}

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
                  <FoldAmount currency={w.currency} value={formatMoney(cm.monthly_free_cash)} size="lg" tone="positive" />
                </View>
              </FoldCard>
            </View>
          );
        })}

        {/* ============================================================
           3. Financial Commitments — reserved lien + active list
        ============================================================ */}
        <View style={styles.blockGap} testID="finance-commitments">
          <FoldSectionHeader
            label="Commitments"
            action={{ label: "New", onPress: () => router.push("/finance/commitments/new") }}
          />
          {reserved.length === 0 && activeCommitments.length === 0 ? (
            <FoldCard>
              <View style={styles.emptyRow}>
                <Text style={styles.emptyRowText}>No financial commitments yet.</Text>
              </View>
            </FoldCard>
          ) : (
            <>
              {reserved.length > 0 || liquidity.length > 0 ? (
                <FoldCard>
                  {reserved.map((r: any, idx: number) => (
                    <FoldRow
                      key={`res-${r.currency}`}
                      first={idx === 0}
                      label={`Reserved (${r.currency})`}
                      meta={`${r.commitments.length} commitment${r.commitments.length === 1 ? "" : "s"} · lien on liquidity`}
                      right={<FoldAmount currency={r.currency} value={formatMoney(r.reserved_total)} />}
                      onPress={() => router.push(`/finance/commitments?currency=${r.currency}&state=reserved`)}
                      chevron
                      testID={`reserved-${r.currency}`}
                    />
                  ))}
                  {liquidity.map((l: any) => (
                    <FoldRow
                      key={`liq-${l.currency}`}
                      label={`Available (${l.currency})`}
                      meta="Liquid minus reservations"
                      right={<FoldAmount currency={l.currency} value={formatMoney(l.available_unreserved)} size="md" tone="positive" />}
                    />
                  ))}
                  {liquidity.map((l: any) => (
                    (l.pending_account_events && l.pending_account_events.length > 0) ? (
                      <FoldRow
                        key={`pending-${l.currency}`}
                        label={`Pending account (${l.currency})`}
                        meta={`${l.pending_account_events.length} spend${l.pending_account_events.length === 1 ? "" : "s"} waiting for an account`}
                        right={<FoldPill label="Assign" tone="warn" size="xs" />}
                        onPress={() => router.push(`/finance/events`)}
                        chevron
                        testID={`pending-account-${l.currency}`}
                      />
                    ) : null
                  ))}
                </FoldCard>
              ) : null}
              {activeCommitments.length > 0 ? (
                <FoldCard style={{ marginTop: financeSpace.md }}>
                  {activeCommitments.slice(0, 6).map((c: any, idx: number) => (
                    <FoldRow
                      key={c.id}
                      first={idx === 0}
                      onPress={() => router.push(`/finance/commitments/${c.id}`)}
                      testID={`commitment-${c.id}`}
                      chevron
                      label={
                        <View style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                          <Text style={[financeType.rowLabel, { maxWidth: 200 }]} numberOfLines={1}>{c.title}</Text>
                          <FoldPill label={STATE_LABEL[c.state] || c.state} tone={STATE_TONE[c.state] || "neutral"} size="xs" />
                          {c.is_overdue ? <FoldPill label="Overdue" tone="err" size="xs" /> : null}
                        </View>
                      }
                      meta={`Due ${dateLabel(c.due_date)}`}
                      right={<FoldAmount currency={c.currency} value={formatMoney(c.amount)} />}
                    />
                  ))}
                  {activeCommitments.length > 6 ? (
                    <Pressable onPress={() => router.push("/finance/commitments")} style={styles.moreRow}>
                      <Text style={styles.moreText}>See all {activeCommitments.length}</Text>
                      <Ionicons name="chevron-forward" size={14} color={financeColors.accent} />
                    </Pressable>
                  ) : null}
                </FoldCard>
              ) : null}
            </>
          )}
        </View>

        {/* ============================================================
           4. Twelve-month forecast — liquidity + net worth twin
        ============================================================ */}
        {(dash?._twin?.liquidity_forecast?.by_currency || []).map((f: any) => {
          const nw = dash._twin.net_worth_forecast.by_currency.find((x: any) => x.currency === f.currency);
          return (
            <View key={`fc-${f.currency}`} style={styles.blockGap} testID={`finance-forecast-${f.currency}`}>
              <FoldSectionHeader
                label="Twelve-month forecast"
                hint={`${f.currency} · liquidity ${f.confidence}${nw?.confidence ? ` · net worth ${nw.confidence}` : ""}`}
                action={{ label: "Full forecast", onPress: () => router.push(`/finance/forecast?currency=${f.currency}`) }}
              />
              <FoldCard>
                <View style={styles.subHead}>
                  <Text style={styles.subHeadText}>Liquidity — can obligations be met?</Text>
                </View>
                {f.months.slice(0, 4).map((m: any, idx: number) => (
                  <FoldRow
                    key={`liq-${m.month}`}
                    first={idx === 0}
                    label={monthLabel(m.month)}
                    meta={`Opening ${formatMoney(m.opening_liquid_money)} · closing ${formatMoney(m.closing_liquid_money)} · ${m.confidence}`}
                    right={<FoldAmount currency={f.currency} value={formatMoney(m.available_unreserved_liquid_money)} tone={m.shortfall ? "negative" : "ink"} />}
                    onPress={() => router.push(`/finance/forecast-month?currency=${f.currency}&month=${m.month}`)}
                    chevron
                  />
                ))}
              </FoldCard>
              {nw?.months?.length > 0 ? (
                <FoldCard style={{ marginTop: financeSpace.md }}>
                  <View style={styles.subHead}>
                    <Text style={styles.subHeadText}>Net worth — how does wealth change?</Text>
                  </View>
                  {nw.months.slice(0, 4).map((m: any, idx: number) => (
                    <FoldRow
                      key={`nw-${m.month}`}
                      first={idx === 0}
                      label={monthLabel(m.month)}
                      meta={`Assets Δ ${formatMoney(m.asset_changes)} · liab Δ ${formatMoney(m.liability_changes)}`}
                      right={<FoldAmount currency={f.currency} value={formatMoney(m.net_worth)} />}
                    />
                  ))}
                </FoldCard>
              ) : null}
            </View>
          );
        })}

        {/* ============================================================
           5. Scenarios & Expected income — quick links
        ============================================================ */}
        {position.length > 0 ? (
          <View style={styles.blockGap}>
            <FoldSectionHeader label="Planning" />
            <FoldCard>
              <FoldRow
                first
                label="Scenarios"
                meta="Simulate salary, spend and one-off changes. Sandbox never touches real data."
                onPress={() => router.push(`/finance/scenarios-index`)}
                chevron
                testID="finance-scenarios"
              />
              <FoldRow
                label="Expected income"
                meta="One-time future income. Expected items need confirmation before entering the forecast."
                onPress={() => router.push(`/finance/expected-income`)}
                chevron
                testID="finance-expected-income"
              />
            </FoldCard>
          </View>
        ) : null}

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
});
