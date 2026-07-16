import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

export default function ForecastMonth() {
  const router = useRouter();
  const { currency, month } = useLocalSearchParams<{ currency: string; month: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinanceForecast()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.by_currency?.find((c: any) => c.currency === currency);
  const m = cur?.months?.find((x: any) => x.month === month);
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title={monthLabel(month || "")} subtitle={`${currency} · forecast detail`} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.kpi}>{currency} {formatMoney(m?.projected_liquid_end_of_month || "0")}</Text>
          <Text style={styles.sub}>Projected liquid end of month{m?.shortfall ? " · shortfall" : ""}</Text>
          <Text style={styles.section}>Assumptions</Text>
          {[
            ["Recurring Income", m?.recurring_income],
            ["Recurring Outflows", m?.recurring_outflows],
            ["Reserved Commitments", m?.reserved_commitments_amount],
            ["Projected Net Worth EoM", m?.projected_net_worth_end_of_month],
          ].map(([label, val]) => (
            <View key={String(label)} style={styles.row}>
              <Text style={styles.rowLabel}>{label}</Text>
              <Text style={styles.rowValue}>{currency} {formatMoney(String(val || "0"))}</Text>
            </View>
          ))}
          <Text style={styles.section}>Contributing commitments</Text>
          {(m?.reserved_commitment_ids || []).map((id: string) => (
            <Pressable key={id} style={styles.linkRow} onPress={() => router.push(`/finance/commitments/${id}`)} testID={`fm-commit-${id}`}>
              <Text style={styles.linkText}>Open commitment</Text>
            </Pressable>
          ))}
          {(!m?.reserved_commitment_ids || m.reserved_commitment_ids.length === 0) && <Text style={styles.empty}>No reserved commitments this month.</Text>}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  kpi: { fontSize: 28, fontWeight: "700", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary },
  section: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.md },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm },
  rowLabel: { fontSize: 13, color: colors.onSurface, fontWeight: "500" },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  linkRow: { padding: spacing.md, backgroundColor: colors.brandTertiary, borderRadius: radius.sm },
  linkText: { color: colors.brandPrimary, fontSize: 13, fontWeight: "600" },
  empty: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic" },
});
