import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

const BUCKET_LABELS: Record<string, string> = {
  income: "Recurring Income",
  expense: "Recurring Expenses",
  debt_payment: "Debt Payments",
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
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title={BUCKET_LABELS[bucket] || bucket} subtitle={`${currency} · ${monthLabel(month)}`} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {items.length === 0 && <Text style={styles.empty}>No commitments in this bucket for {monthLabel(month)}.</Text>}
          {items.map((it: any) => (
            <View key={it.id} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>{it.title}</Text>
                <Text style={styles.rowMeta}>{it.fixed_or_flexible} · from {it.start_month}{it.end_month ? ` → ${it.end_month}` : ""}</Text>
              </View>
              <Text style={styles.rowValue}>{currency} {formatMoney(it.amount)}</Text>
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  row: { flexDirection: "row", alignItems: "center", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowLabel: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", textAlign: "center", padding: spacing.xl },
});
