import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace, financeType } from "@/src/lib/finance/theme";
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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Monthly commitments" subtitle={currency} />
      <View style={styles.nav}>
        <Pressable onPress={() => goto(addMonth(month, -1))} hitSlop={12} testID="month-prev" style={styles.navBtn}>
          <Ionicons name="chevron-back" size={18} color={financeColors.ink} />
        </Pressable>
        <Text style={styles.monthLabel}>{monthLabel(month)}</Text>
        <Pressable onPress={() => goto(addMonth(month, 1))} hitSlop={12} testID="month-next" style={styles.navBtn}>
          <Ionicons name="chevron-forward" size={18} color={financeColors.ink} />
        </Pressable>
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <FoldCard>
            {[
              { label: "Recurring income", val: data?.recurring_income, bucket: "income", tone: "positive" as const },
              { label: "Recurring expenses", val: data?.recurring_expenses, bucket: "expense", tone: "ink" as const },
              { label: "Debt payments", val: data?.debt_payments, bucket: "debt_payment", tone: "ink" as const },
              { label: "Savings", val: data?.savings, bucket: "saving", tone: "ink" as const },
              { label: "Investments", val: data?.investments, bucket: "investment", tone: "ink" as const },
            ].map((r, idx) => (
              <FoldRow
                key={r.label}
                first={idx === 0}
                label={r.label}
                right={<FoldAmount currency={currency} value={formatMoney(r.val || "0")} tone={r.tone} />}
                onPress={() => router.push(`/finance/monthly-drill?currency=${currency}&month=${month}&bucket=${r.bucket}`)}
                chevron
                testID={`monthly-${r.bucket}`}
              />
            ))}
          </FoldCard>

          <View style={styles.freeCash}>
            <Text style={styles.freeCashLabel}>Free cash</Text>
            <FoldAmount currency={currency} value={formatMoney(data?.monthly_free_cash || "0")} size="xl" tone="positive" />
          </View>
          <Text style={styles.formula}>Free cash = income − expenses − debt − savings − investments</Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  nav: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: financeSpace.xl,
    paddingBottom: financeSpace.md,
  },
  navBtn: { width: 34, height: 34, alignItems: "center", justifyContent: "center", borderRadius: 999, backgroundColor: "#FFFFFF", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  monthLabel: { fontFamily: "Georgia", fontSize: 18, fontWeight: "700", color: financeColors.ink, letterSpacing: -0.2 },
  scroll: { padding: financeSpace.xl, paddingTop: 0, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  freeCash: {
    marginTop: financeSpace.md,
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: financeColors.cardBorder,
    padding: financeSpace.lg,
    alignItems: "center",
    gap: financeSpace.xs,
  },
  freeCashLabel: { ...financeType.sectionLabel } as any,
  formula: { fontSize: 11.5, color: financeColors.inkMuted, textAlign: "center", fontStyle: "italic", letterSpacing: 0.3 },
});
