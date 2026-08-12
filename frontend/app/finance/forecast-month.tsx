import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldHero, FoldPill, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={monthLabel(month || "")} subtitle={`${currency} · forecast detail`} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldHero currency={currency} amount={formatMoney(m?.projected_liquid_end_of_month || "0")} size="xl" caption="Projected liquid end of month" />
          {m?.shortfall ? <FoldPill label="Shortfall" tone="err" /> : null}

          <FoldSectionHeader label="Assumptions" />
          <FoldCard>
            {[
              ["Recurring income", m?.recurring_income],
              ["Recurring outflows", m?.recurring_outflows],
              ["Reserved commitments", m?.reserved_commitments_amount],
              ["Projected net worth EoM", m?.projected_net_worth_end_of_month],
            ].map(([label, val], idx) => (
              <FoldRow
                key={String(label)}
                first={idx === 0}
                label={String(label)}
                right={<FoldAmount currency={currency} value={formatMoney(String(val || "0"))} />}
              />
            ))}
          </FoldCard>

          <FoldSectionHeader label="Contributing commitments" />
          {(m?.reserved_commitment_ids || []).length === 0 ? (
            <FoldCard><Text style={styles.empty}>No reserved commitments this month.</Text></FoldCard>
          ) : (
            <FoldCard>
              {(m?.reserved_commitment_ids || []).map((id: string, idx: number) => (
                <Pressable
                  key={id}
                  style={[styles.linkRow, idx > 0 && styles.rowDivider]}
                  onPress={() => router.push(`/finance/commitments/${id}`)}
                  testID={`fm-commit-${id}`}
                >
                  <Text style={styles.linkText}>Open commitment</Text>
                </Pressable>
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
  linkRow: { padding: financeSpace.lg, backgroundColor: "#FFFFFF" },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  linkText: { fontSize: 13, color: financeColors.accent, fontWeight: "600" },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.lg, fontStyle: "italic", textAlign: "center" },
});
