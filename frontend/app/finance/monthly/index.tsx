import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { currentMonthIso, formatMoney, monthLabel } from "@/src/lib/finance/format";

function addMonth(m: string, delta: number): string {
  const [y, mo] = m.split("-");
  let yi = parseInt(y, 10);
  let mi = parseInt(mo, 10) + delta;
  while (mi < 1) { mi += 12; yi -= 1; }
  while (mi > 12) { mi -= 12; yi += 1; }
  return `${yi.toString().padStart(4, "0")}-${mi.toString().padStart(2, "0")}`;
}

export default function MonthlyBrowse() {
  const router = useRouter();
  const { currency, month: monthParam } = useLocalSearchParams<{ currency: string; month?: string }>();
  const [month, setMonth] = useState<string>(monthParam || currentMonthIso());
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (m: string) => {
    setLoading(true);
    try { setData(await api.getFinanceMonthly(m, currency)); } catch { /* ignore */ }
    setLoading(false);
  }, [currency]);

  useEffect(() => { load(month); }, [load, month]);

  const goto = (m: string) => setMonth(m);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Monthly Commitments" subtitle={`${currency}`} />
      <View style={styles.nav}>
        <Pressable onPress={() => goto(addMonth(month, -1))} hitSlop={12} testID="month-prev">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.monthLabel}>{monthLabel(month)}</Text>
        <Pressable onPress={() => goto(addMonth(month, 1))} hitSlop={12} testID="month-next">
          <Ionicons name="chevron-forward" size={22} color={colors.onSurface} />
        </Pressable>
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {[
            { label: "Recurring Income", val: data?.recurring_income, bucket: "income" },
            { label: "Recurring Expenses", val: data?.recurring_expenses, bucket: "expense" },
            { label: "Debt Payments", val: data?.debt_payments, bucket: "debt_payment" },
            { label: "Savings", val: data?.savings, bucket: "saving" },
            { label: "Investments", val: data?.investments, bucket: "investment" },
          ].map((r) => (
            <Pressable key={r.label} style={styles.row} onPress={() => router.push(`/finance/monthly-drill?currency=${currency}&month=${month}&bucket=${r.bucket}`)} testID={`monthly-${r.bucket}`}>
              <Text style={styles.rowLabel}>{r.label}</Text>
              <Text style={styles.rowValue}>{currency} {formatMoney(r.val || "0")}</Text>
              <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
          <View style={styles.freeRow}>
            <Text style={styles.freeLabel}>Monthly Free Cash</Text>
            <Text style={styles.freeValue}>{currency} {formatMoney(data?.monthly_free_cash || "0")}</Text>
          </View>
          <Text style={styles.footNote}>Free Cash = Income − Expenses − Debt − Savings − Investments</Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  nav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingBottom: spacing.md },
  monthLabel: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  scroll: { padding: spacing.xl, paddingTop: 0, gap: spacing.sm, paddingBottom: spacing.xxxl },
  row: { flexDirection: "row", alignItems: "center", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowLabel: { flex: 1, fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  freeRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.onSurface, borderRadius: radius.md, marginTop: spacing.md },
  freeLabel: { fontSize: 14, color: colors.onSurfaceInverse, fontWeight: "600" },
  freeValue: { fontSize: 18, color: colors.onSurfaceInverse, fontWeight: "700" },
  footNote: { fontSize: 11, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: spacing.sm, fontStyle: "italic" },
});
