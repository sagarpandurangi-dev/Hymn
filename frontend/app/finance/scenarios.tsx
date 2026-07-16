import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

export default function Scenarios() {
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [addExp, setAddExp] = useState("");
  const [addInc, setAddInc] = useState("");
  const [addRes, setAddRes] = useState("");
  const [resMonth, setResMonth] = useState("");
  const [result, setResult] = useState<any | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => { setResult(null); }, [currency]);

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.runFinanceScenario({
        currency,
        additional_monthly_expense: addExp || undefined,
        additional_monthly_income: addInc || undefined,
        additional_reservation: addRes || undefined,
        reservation_due_month: resMonth || undefined,
      });
      setResult(r);
    } catch { /* ignore */ }
    setRunning(false);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Scenarios" subtitle={`What if… (${currency})`} />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.help}>Enter one or more levers below. We’ll re-run the 12-month forecast with your assumptions applied and show the delta.</Text>
          <Text style={styles.label}>Additional monthly expense</Text>
          <TextInput value={addExp} onChangeText={setAddExp} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="sc-exp" />
          <Text style={styles.label}>Additional monthly income</Text>
          <TextInput value={addInc} onChangeText={setAddInc} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="sc-inc" />
          <Text style={styles.label}>One-off reservation</Text>
          <TextInput value={addRes} onChangeText={setAddRes} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="sc-res" />
          <Text style={styles.label}>Reservation due month (YYYY-MM)</Text>
          <TextInput value={resMonth} onChangeText={setResMonth} placeholder="2026-11" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="sc-res-month" />

          <Pressable style={[styles.primary, running && { opacity: 0.5 }]} disabled={running} onPress={run} testID="sc-run"><Text style={styles.primaryText}>{running ? "Running…" : "Run scenario"}</Text></Pressable>

          {running && <ActivityIndicator style={{ marginTop: spacing.md }} />}

          {result?.months?.length > 0 && (
            <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
              <Text style={styles.section}>Comparison</Text>
              {result.months.map((m: any) => (
                <View key={m.month} style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowLabel}>{monthLabel(m.month)}</Text>
                    <Text style={styles.rowMeta}>Original {currency} {formatMoney(m.original_projected_liquid)}</Text>
                  </View>
                  <Text style={styles.rowValue}>{currency} {formatMoney(m.scenario_projected_liquid)}</Text>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  help: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 18 },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.md },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", marginTop: spacing.lg },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "700" },
  section: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowLabel: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
});
