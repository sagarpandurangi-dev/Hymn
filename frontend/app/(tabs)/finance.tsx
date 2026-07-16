/**
 * Finance tab — the financial dashboard, forecasting and decision layer.
 *
 * Every KPI, total and chart is drillable. The screen only fetches a
 * single ``GET /api/finance/dashboard`` and renders what the backend
 * returned — no math on the client.
 */
import { useCallback, useEffect, useState } from "react";
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
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import HeaderAvatar from "@/src/components/HeaderAvatar";
import {
  currentMonthIso,
  dateLabel,
  formatMoney,
  monthLabel,
  stateColor,
  stateLabel,
} from "@/src/lib/finance/format";

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
      <SafeAreaView style={styles.safe} edges={["top"]} testID="finance-screen">
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Finance</Text>
          <HeaderAvatar />
        </View>
        <ActivityIndicator style={{ marginTop: spacing.xxxl }} color={colors.brandPrimary} />
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
    <SafeAreaView style={styles.safe} edges={["top"]} testID="finance-screen">
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Finance</Text>
        <HeaderAvatar />
      </View>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {error && <Text style={styles.error}>{error}</Text>}

        {position.length === 0 && (
          <View style={styles.emptyCard}>
            <Ionicons name="wallet-outline" size={36} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>Set up your Portfolio first</Text>
            <Text style={styles.emptyBody}>
              Finance mirrors your Portfolio in real time. Add accounts and monthly commitments in
              Portfolio to see your dashboard populate here.
            </Text>
            <Pressable style={styles.emptyCta} onPress={() => router.push("/portfolio")} testID="finance-open-portfolio">
              <Text style={styles.emptyCtaText}>Open Portfolio</Text>
            </Pressable>
          </View>
        )}

        {multiCurrency && (
          <Text style={styles.notice} testID="finance-fx-notice">
            {dash?.position?.notice}
          </Text>
        )}

        {dueForReview.length > 0 && (
          <View style={styles.reviewBanner} testID="finance-review-banner">
            <Ionicons name="alarm-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.reviewBannerText}>
              {dueForReview.length} Financial Commitment{dueForReview.length === 1 ? "" : "s"} due for review
            </Text>
            <Pressable onPress={() => router.push("/finance/reviews")} hitSlop={12} testID="finance-open-reviews">
              <Text style={styles.reviewCta}>Review</Text>
            </Pressable>
          </View>
        )}

        {dash?._recon_count > 0 && (
          <View style={styles.reviewBanner} testID="finance-recon-banner">
            <Ionicons name="git-compare-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.reviewBannerText}>
              {dash._recon_count} confirmed event{dash._recon_count === 1 ? "" : "s"} awaiting reconciliation
            </Text>
            <Pressable onPress={() => router.push("/finance/reconciliation")} hitSlop={12} testID="finance-open-recon">
              <Text style={styles.reviewCta}>Reconcile</Text>
            </Pressable>
          </View>
        )}

        {/* ============================================================
           1. Current Financial Position
           ============================================================ */}
        {position.map((cur: any) => (
          <Section
            key={`pos-${cur.currency}`}
            title="Current Financial Position"
            subtitle={cur.currency}
            testID={`finance-position-${cur.currency}`}
          >
            <View style={styles.kpiGrid}>
              <Kpi
                label="Total Assets"
                value={`${cur.currency} ${formatMoney(cur.total_assets)}`}
                onPress={() => router.push(`/finance/position/assets?currency=${cur.currency}`)}
                testID={`kpi-total-assets-${cur.currency}`}
              />
              <Kpi
                label="Total Liabilities"
                value={`${cur.currency} ${formatMoney(cur.total_liabilities)}`}
                onPress={() => router.push(`/finance/position/liabilities?currency=${cur.currency}`)}
                testID={`kpi-total-liabilities-${cur.currency}`}
              />
              <Kpi
                label="Net Worth"
                value={`${cur.currency} ${formatMoney(cur.net_worth)}`}
                highlight
                onPress={() => router.push(`/finance/position/net-worth?currency=${cur.currency}`)}
                testID={`kpi-net-worth-${cur.currency}`}
              />
              <Kpi
                label="Liquid Assets"
                value={`${cur.currency} ${formatMoney(cur.liquid_assets)}`}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=liquid`)}
                testID={`kpi-liquid-${cur.currency}`}
              />
              <Kpi
                label="Semi-Liquid"
                value={`${cur.currency} ${formatMoney(cur.semi_liquid_assets)}`}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=semi_liquid`)}
                testID={`kpi-semi-liquid-${cur.currency}`}
              />
              <Kpi
                label="Illiquid"
                value={`${cur.currency} ${formatMoney(cur.illiquid_assets)}`}
                onPress={() => router.push(`/finance/position/liquidity?currency=${cur.currency}&bucket=illiquid`)}
                testID={`kpi-illiquid-${cur.currency}`}
              />
            </View>
          </Section>
        ))}

        {/* ============================================================
           2. Monthly Commitments (current month per currency)
           ============================================================ */}
        {monthlyWindows.map((w: any) => {
          const cm = w.months?.[0];
          if (!cm) return null;
          return (
            <Section
              key={`mm-${w.currency}`}
              title="Monthly Commitments"
              subtitle={`${w.currency} · ${monthLabel(cm.month)}`}
              testID={`finance-monthly-${w.currency}`}
              action={{
                label: "Browse months",
                onPress: () => router.push(`/finance/monthly?currency=${w.currency}`),
              }}
            >
              <View style={styles.kpiGrid}>
                <Kpi
                  label="Recurring Income"
                  value={`${w.currency} ${formatMoney(cm.recurring_income)}`}
                  onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=income`)}
                />
                <Kpi
                  label="Recurring Expenses"
                  value={`${w.currency} ${formatMoney(cm.recurring_expenses)}`}
                  onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=expense`)}
                />
                <Kpi
                  label="Debt Payments"
                  value={`${w.currency} ${formatMoney(cm.debt_payments)}`}
                  onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=debt_payment`)}
                />
                <Kpi
                  label="Savings"
                  value={`${w.currency} ${formatMoney(cm.savings)}`}
                  onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=saving`)}
                />
                <Kpi
                  label="Investments"
                  value={`${w.currency} ${formatMoney(cm.investments)}`}
                  onPress={() => router.push(`/finance/monthly-drill?currency=${w.currency}&month=${cm.month}&bucket=investment`)}
                />
                <Kpi
                  label="Monthly Free Cash"
                  value={`${w.currency} ${formatMoney(cm.monthly_free_cash)}`}
                  highlight
                  onPress={() => router.push(`/finance/monthly?currency=${w.currency}&month=${cm.month}`)}
                />
              </View>
            </Section>
          );
        })}

        {/* ============================================================
           3. Financial Commitments (Reserved + reserved-money lien)
           ============================================================ */}
        <Section
          title="Financial Commitments"
          testID="finance-commitments"
          action={{
            label: "New",
            onPress: () => router.push("/finance/commitments/new"),
          }}
        >
          {reserved.length === 0 && activeCommitments.length === 0 && (
            <Text style={styles.emptyBody}>No Financial Commitments yet.</Text>
          )}
          {reserved.map((r: any) => (
            <Pressable
              key={`res-${r.currency}`}
              style={styles.reservedRow}
              onPress={() => router.push(`/finance/commitments?currency=${r.currency}&state=reserved`)}
              testID={`reserved-${r.currency}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.reservedLabel}>Reserved ({r.currency})</Text>
                <Text style={styles.reservedMeta}>
                  {r.commitments.length} commitment{r.commitments.length === 1 ? "" : "s"} · tap to see the lien
                </Text>
              </View>
              <Text style={styles.reservedValue}>{r.currency} {formatMoney(r.reserved_total)}</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
          {liquidity.map((l: any) => (
            <View key={`liq-${l.currency}`} style={styles.liquidityRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.reservedLabel}>Available unreserved ({l.currency})</Text>
                <Text style={styles.reservedMeta}>Liquid minus reservations & spend this month</Text>
              </View>
              <Text style={styles.reservedValueStrong}>{l.currency} {formatMoney(l.available_unreserved)}</Text>
            </View>
          ))}
          {activeCommitments.slice(0, 6).map((c: any) => (
            <Pressable
              key={c.id}
              style={styles.commitmentRow}
              onPress={() => router.push(`/finance/commitments/${c.id}`)}
              testID={`commitment-${c.id}`}
            >
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                  <Text style={styles.commitmentTitle} numberOfLines={1}>{c.title}</Text>
                  <View style={[styles.stateChip, { backgroundColor: stateColor(c.state) }]}>
                    <Text style={styles.stateChipText}>{stateLabel(c.state)}</Text>
                  </View>
                </View>
                <Text style={styles.commitmentMeta}>
                  {c.currency} {formatMoney(c.amount)} · due {dateLabel(c.due_date)}
                  {c.is_overdue ? " · overdue" : ""}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
          {activeCommitments.length > 6 && (
            <Pressable onPress={() => router.push("/finance/commitments")} style={styles.linkRow}>
              <Text style={styles.linkText}>See all {activeCommitments.length}</Text>
            </Pressable>
          )}
        </Section>

        {/* ============================================================
           4. Twelve-Month Forecast (twin: liquidity + net worth §18–§20)
           ============================================================ */}
        {(dash?._twin?.liquidity_forecast?.by_currency || []).map((f: any) => {
          const nw = dash._twin.net_worth_forecast.by_currency.find((x: any) => x.currency === f.currency);
          return (
            <Section
              key={`fc-${f.currency}`}
              title="Twelve-Month Forecast"
              subtitle={`${f.currency} · liquidity ${f.confidence} · net worth ${nw?.confidence || "—"}`}
              testID={`finance-forecast-${f.currency}`}
              action={{
                label: "Full forecast",
                onPress: () => router.push(`/finance/forecast?currency=${f.currency}`),
              }}
            >
              <Text style={styles.notice}>Liquidity — “can obligations be met?”</Text>
              {f.months.slice(0, 4).map((m: any) => (
                <Pressable
                  key={`liq-${m.month}`}
                  style={styles.forecastRow}
                  onPress={() => router.push(`/finance/forecast-month?currency=${f.currency}&month=${m.month}`)}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.forecastMonth}>{monthLabel(m.month)}</Text>
                    <Text style={styles.forecastMeta}>
                      opening {formatMoney(m.opening_liquid_money)} · closing {formatMoney(m.closing_liquid_money)} · {m.confidence}
                    </Text>
                  </View>
                  <Text style={[styles.forecastVal, m.shortfall && { color: colors.error }]}>
                    {f.currency} {formatMoney(m.available_unreserved_liquid_money)}
                  </Text>
                </Pressable>
              ))}
              {nw?.months?.length > 0 && (
                <>
                  <Text style={styles.notice}>Net Worth — “how does wealth change?”</Text>
                  {nw.months.slice(0, 4).map((m: any) => (
                    <View key={`nw-${m.month}`} style={styles.forecastRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.forecastMonth}>{monthLabel(m.month)}</Text>
                        <Text style={styles.forecastMeta}>
                          assets Δ {formatMoney(m.asset_changes)} · liab Δ {formatMoney(m.liability_changes)}
                        </Text>
                      </View>
                      <Text style={styles.forecastVal}>{f.currency} {formatMoney(m.net_worth)}</Text>
                    </View>
                  ))}
                </>
              )}
            </Section>
          );
        })}

        {/* ============================================================
           5. Scenarios (persistent sandbox §26)
           ============================================================ */}
        {position.length > 0 && (
          <Section
            title="Scenarios"
            subtitle="What if… (sandbox never touches real data)"
            testID="finance-scenarios"
            action={{ label: "Open", onPress: () => router.push(`/finance/scenarios-index`) }}
          >
            <Text style={styles.emptyBody}>
              Simulate a new monthly expense, salary change, one-off reservation or loan closure and compare against the
              base forecast. Save scenarios, duplicate them, rename or delete — nothing changes your Portfolio.
            </Text>
          </Section>
        )}

        {position.length > 0 && (
          <Section
            title="Expected income"
            subtitle="One-time future income · confirmed vs expected"
            testID="finance-expected-income"
            action={{ label: "Open", onPress: () => router.push(`/finance/expected-income`) }}
          >
            <Text style={styles.emptyBody}>
              Treat future income cautiously until it has been earned. Expected items need a second confirmation before
              entering the forecast.
            </Text>
          </Section>
        )}

        {/* ============================================================
           6. Recent Actual Financial Events
           ============================================================ */}
        <Section
          title="Recent Actual Financial Events"
          testID="finance-events"
          action={{ label: "All events", onPress: () => router.push("/finance/events") }}
        >
          {recentEvents.length === 0 && (
            <Text style={styles.emptyBody}>Check-ins with money spent, imports and manual events appear here.</Text>
          )}
          {recentEvents.slice(0, 8).map((e: any) => (
            <Pressable
              key={e.id}
              style={styles.eventRow}
              onPress={() => router.push(`/finance/events/${e.id}`)}
              testID={`event-${e.id}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.eventTitle} numberOfLines={1}>{e.description || "(no description)"}</Text>
                <Text style={styles.eventMeta}>
                  {dateLabel(e.event_date)} · {e.source} · {e.direction}
                </Text>
              </View>
              <Text style={[styles.eventAmount, e.direction === "inflow" ? { color: colors.success } : { color: colors.onSurface }]}>
                {e.direction === "outflow" ? "-" : "+"}{e.currency} {formatMoney(e.amount)}
              </Text>
            </Pressable>
          ))}
        </Section>

        <Text style={styles.footerNote}>
          Generated: {dash?.generated_at?.slice(0, 16).replace("T", " ")} UTC · uses month {currentMonthIso()}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

// ============================================================================
// Helper components
// ============================================================================

function Section({
  title, subtitle, testID, action, children,
}: {
  title: string; subtitle?: string; testID?: string;
  action?: { label: string; onPress: () => void };
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section} testID={testID}>
      <View style={styles.sectionHeader}>
        <View style={{ flex: 1 }}>
          <Text style={styles.sectionTitle}>{title}</Text>
          {subtitle && <Text style={styles.sectionSubtitle}>{subtitle}</Text>}
        </View>
        {action && (
          <Pressable onPress={action.onPress} hitSlop={12}>
            <Text style={styles.linkText}>{action.label}</Text>
          </Pressable>
        )}
      </View>
      {children}
    </View>
  );
}

function Kpi({
  label, value, onPress, highlight, testID,
}: {
  label: string; value: string; onPress?: () => void; highlight?: boolean; testID?: string;
}) {
  return (
    <Pressable style={[styles.kpi, highlight && styles.kpiHighlight]} onPress={onPress} testID={testID}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={[styles.kpiValue, highlight && styles.kpiValueHighlight]}>{value}</Text>
      {onPress && <Ionicons name="chevron-forward" size={12} color={colors.onSurfaceTertiary} style={styles.kpiChev} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.lg },
  error: { color: colors.error, fontSize: 13 },
  notice: {
    fontSize: 12, color: colors.onSurfaceSecondary, backgroundColor: colors.brandTertiary,
    padding: spacing.md, borderRadius: radius.sm,
  },
  emptyCard: {
    alignItems: "center", padding: spacing.xl, gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
  },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface, textAlign: "center" },
  emptyBody: { fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 18 },
  emptyCta: {
    backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
    borderRadius: radius.pill,
  },
  emptyCtaText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "600" },
  reviewBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.brandTertiary, borderRadius: radius.md,
  },
  reviewBannerText: { flex: 1, fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  reviewCta: { color: colors.brandPrimary, fontSize: 13, fontWeight: "700" },
  section: { gap: spacing.md },
  sectionHeader: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  sectionTitle: { fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  sectionSubtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2, letterSpacing: 0.5 },
  linkText: { color: colors.brandPrimary, fontSize: 13, fontWeight: "600" },
  linkRow: { paddingVertical: spacing.sm, alignItems: "center" },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpi: {
    flexBasis: "48%", flexGrow: 1,
    padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    position: "relative",
  },
  kpiHighlight: { backgroundColor: colors.onSurface },
  kpiLabel: { fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  kpiValue: { fontSize: 18, color: colors.onSurface, fontWeight: "700", marginTop: 4 },
  kpiValueHighlight: { color: colors.onSurfaceInverse },
  kpiChev: { position: "absolute", top: spacing.md, right: spacing.md },
  reservedRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
  },
  liquidityRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.brandTertiary, borderRadius: radius.md,
  },
  reservedLabel: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  reservedMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  reservedValue: { fontSize: 16, color: colors.onSurface, fontWeight: "700" },
  reservedValueStrong: { fontSize: 18, color: colors.brandPrimary, fontWeight: "700" },
  commitmentRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
  },
  commitmentTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  commitmentMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  stateChip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill },
  stateChipText: { fontSize: 10, color: "#fff", fontWeight: "700", letterSpacing: 0.5 },
  forecastRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
  },
  forecastMonth: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  forecastMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  forecastVal: { fontSize: 15, color: colors.onSurface, fontWeight: "700" },
  eventRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
  },
  eventTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "500" },
  eventMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  eventAmount: { fontSize: 14, fontWeight: "700" },
  footerNote: { fontSize: 10, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: spacing.md },
});
