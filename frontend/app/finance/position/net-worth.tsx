import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldHero, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

export default function NetWorthDrill() {
  const router = useRouter();
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinancePosition()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Net worth" subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldHero
            currency={currency}
            amount={formatMoney(cur?.net_worth || "0")}
            size="xl"
            caption="Total assets minus total liabilities"
          />

          <FoldSectionHeader label="Breakdown" />
          <FoldCard>
            <FoldRow
              first
              label="Total assets"
              meta="Tap for asset breakdown"
              right={<FoldAmount currency={currency} value={formatMoney(cur?.total_assets || "0")} />}
              onPress={() => router.push(`/finance/position/assets?currency=${currency}`)}
              chevron
              testID="nw-assets-drill"
            />
            <FoldRow
              label="Total liabilities"
              meta="Tap for liability breakdown"
              right={<FoldAmount currency={currency} value={formatMoney(cur?.total_liabilities || "0")} />}
              onPress={() => router.push(`/finance/position/liabilities?currency=${currency}`)}
              chevron
              testID="nw-liabilities-drill"
            />
          </FoldCard>

          <Text style={styles.formula}>Net Worth = Total Assets − Total Liabilities</Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  formula: { fontSize: 11.5, color: financeColors.inkMuted, fontStyle: "italic", textAlign: "center", letterSpacing: 0.3 },
});
