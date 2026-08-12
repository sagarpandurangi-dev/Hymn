import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldHero, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

export default function LiabilitiesDrill() {
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinancePosition()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Total liabilities" subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldHero currency={currency} amount={formatMoney(cur?.total_liabilities || "0")} size="xl" />

          <FoldSectionHeader label="Contributing accounts" />
          {(cur?.accounts_liability || []).length === 0 ? (
            <FoldCard><Text style={styles.empty}>No liabilities in {currency}.</Text></FoldCard>
          ) : (
            <FoldCard>
              {(cur?.accounts_liability || []).map((a: any, idx: number) => (
                <FoldRow
                  key={a.id}
                  first={idx === 0}
                  label={a.name}
                  meta={a.account_type}
                  right={<FoldAmount currency={currency} value={formatMoney(a.current_value)} />}
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
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.lg, fontStyle: "italic" },
});
