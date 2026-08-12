import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldHero, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

const LABELS: Record<string, string> = { liquid: "Liquid assets", semi_liquid: "Semi-liquid assets", illiquid: "Illiquid assets" };

export default function LiquidityDrill() {
  const { currency, bucket } = useLocalSearchParams<{ currency: string; bucket: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinancePosition()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  const accounts = bucket === "liquid" ? cur?.accounts_liquid : bucket === "semi_liquid" ? cur?.accounts_semi_liquid : cur?.accounts_illiquid;
  const total = bucket === "liquid" ? cur?.liquid_assets : bucket === "semi_liquid" ? cur?.semi_liquid_assets : cur?.illiquid_assets;
  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={LABELS[bucket] || "Liquidity"} subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldHero currency={currency} amount={formatMoney(total || "0")} size="xl" />

          <FoldSectionHeader label="Contributing accounts" />
          {(accounts || []).length === 0 ? (
            <FoldCard><Text style={styles.empty}>No accounts in this bucket.</Text></FoldCard>
          ) : (
            <FoldCard>
              {(accounts || []).map((a: any, idx: number) => (
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
