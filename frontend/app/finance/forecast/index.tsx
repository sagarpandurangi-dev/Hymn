import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Twelve-month forecast" subtitle={`${currency} · confidence ${cur?.confidence || "–"}`} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.formula}>Projected liquid = opening liquid + income − outflows − reservations (per month, running).</Text>
          {(cur?.months || []).length === 0 ? (
            <FoldCard><View style={{ padding: financeSpace.lg }}><Text style={styles.empty}>No forecast data yet.</Text></View></FoldCard>
          ) : (
            <FoldCard>
              {(cur?.months || []).map((m: any, idx: number) => (
                <FoldRow
                  key={m.month}
                  first={idx === 0}
                  label={monthLabel(m.month)}
                  meta={`Income ${formatMoney(m.recurring_income)} · outflow ${formatMoney(m.recurring_outflows)} · reserved ${formatMoney(m.reserved_commitments_amount)}`}
                  right={<FoldAmount currency={currency} value={formatMoney(m.projected_liquid_end_of_month)} tone={m.shortfall ? "negative" : "ink"} />}
                  onPress={() => router.push(`/finance/forecast-month?currency=${currency}&month=${m.month}`)}
                  chevron
                  testID={`forecast-row-${m.month}`}
                />
              ))}
            </FoldCard>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  formula: { fontSize: 11.5, color: financeColors.inkMuted, fontStyle: "italic", letterSpacing: 0.3, marginBottom: 4 },
  empty: { fontSize: 13, color: financeColors.inkMuted, textAlign: "center", fontStyle: "italic" },
});
