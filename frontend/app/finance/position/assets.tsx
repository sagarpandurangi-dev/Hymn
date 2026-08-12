import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldHero, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

export default function AssetsDrill() {
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try { setData(await api.getFinancePosition()); } catch { /* ignore */ }
      setLoading(false);
    })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Total assets" subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldHero currency={currency} amount={formatMoney(cur?.total_assets || "0")} size="xl" />

          <FoldSectionHeader label="By liquidity" />
          <FoldCard>
            <FoldRow first label="Liquid" right={<FoldAmount currency={currency} value={formatMoney(cur?.liquid_assets || "0")} />} />
            <FoldRow label="Semi-liquid" right={<FoldAmount currency={currency} value={formatMoney(cur?.semi_liquid_assets || "0")} />} />
            <FoldRow label="Illiquid" right={<FoldAmount currency={currency} value={formatMoney(cur?.illiquid_assets || "0")} />} />
          </FoldCard>

          <FoldSectionHeader label="Contributing accounts" />
          {(cur?.accounts_asset || []).length === 0 ? (
            <FoldCard><Text style={styles.empty}>No asset accounts in {currency}.</Text></FoldCard>
          ) : (
            <FoldCard>
              {(cur?.accounts_asset || []).map((a: any, idx: number) => (
                <FoldRow
                  key={a.id}
                  first={idx === 0}
                  label={a.name}
                  meta={`${a.account_type} · ${a.liquidity_type}`}
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
