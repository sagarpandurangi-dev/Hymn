import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

export default function ForecastFull() {
  const router = useRouter();
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinanceForecast()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.by_currency?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Twelve-Month Forecast" subtitle={`${currency} · confidence: ${cur?.confidence || "–"}`} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.formula}>Projected liquid = opening liquid + income − outflows − reservations (per month, running).</Text>
          {(cur?.months || []).map((m: any) => (
            <Pressable key={m.month} style={[styles.row, m.shortfall && styles.rowShortfall]} onPress={() => router.push(`/finance/forecast-month?currency=${currency}&month=${m.month}`)} testID={`forecast-row-${m.month}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.monthName}>{monthLabel(m.month)}</Text>
                <Text style={styles.monthMeta}>
                  income {formatMoney(m.recurring_income)} · outflow {formatMoney(m.recurring_outflows)} · reserved {formatMoney(m.reserved_commitments_amount)}
                </Text>
              </View>
              <Text style={[styles.monthVal, m.shortfall && { color: colors.error }]}>{currency} {formatMoney(m.projected_liquid_end_of_month)}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  formula: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic", marginBottom: spacing.sm },
  row: { padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.xs, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  rowShortfall: { borderWidth: 1, borderColor: colors.error },
  monthName: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  monthMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  monthVal: { fontSize: 15, color: colors.onSurface, fontWeight: "700" },
});
