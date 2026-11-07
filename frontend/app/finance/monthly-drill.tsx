import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

const BUCKET_LABELS: Record<string, string> = {
  income: "Recurring income",
  expense: "Recurring expenses",
  debt_payment: "Debt payments",
  saving: "Savings",
  investment: "Investments",
};

export default function MonthlyDrill() {
  const { currency, month, bucket } = useLocalSearchParams<{ currency: string; month: string; bucket: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinanceMonthly(month, currency)); } catch { /* ignore */ } setLoading(false); })();
  }, [month, currency]);

  const key = bucket === "income" ? "income_items" : bucket === "expense" ? "expense_items" : bucket === "debt_payment" ? "debt_payment_items" : bucket === "saving" ? "saving_items" : bucket === "investment" ? "investment_items" : "other_items";
  const items: any[] = data?.[key] || [];
  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={BUCKET_LABELS[bucket] || bucket} subtitle={`${currency} · ${monthLabel(month)}`} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {items.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No commitments in this bucket for {monthLabel(month)}.</Text></FoldCard>
          ) : (
            <FoldCard>
              {items.map((it: any, idx: number) => (
                <FoldRow
                  key={it.id}
                  first={idx === 0}
                  label={it.title}
                  meta={`${it.fixed_or_flexible} · from ${it.start_month}${it.end_month ? ` → ${it.end_month}` : ""}`}
                  right={<FoldAmount currency={currency} value={formatMoney(it.amount)} />}
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
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.lg, fontStyle: "italic", textAlign: "center" },
});
