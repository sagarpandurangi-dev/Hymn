import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney, monthLabel } from "@/src/lib/finance/format";

export default function ScenarioDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [scen, setScen] = useState<any | null>(null);
  const [assumptions, setAssumptions] = useState<any>({});
  const [evalResult, setEvalResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.getScenario(id);
      setScen(s);
      setAssumptions(s.assumptions || {});
    } catch { /* ignore */ }
    setLoading(false);
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const setA = (k: string, v: string) => setAssumptions((prev: any) => ({ ...prev, [k]: v }));

  const evaluate = async () => {
    setSaving(true);
    try {
      await api.updateScenario(id, { name: scen.name, currency: scen.currency, assumptions });
      const r = await api.evaluateScenario(id);
      setEvalResult(r);
    } catch { /* ignore */ }
    setSaving(false);
  };

  if (loading || !scen) return (<SafeAreaView style={styles.safe}><FinanceHeader title="Scenario" /><ActivityIndicator style={{ marginTop: spacing.xxxl }} /></SafeAreaView>);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title={scen.name} subtitle={`Sandbox · ${scen.currency}`} />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.help}>Enter one or more levers. Nothing here changes your real Portfolio, Tasks, Check-ins or Financial Commitments.</Text>
          {[
            ["additional_monthly_income", "Additional monthly income"],
            ["additional_monthly_expense", "Additional monthly expense"],
            ["salary_delta", "Salary change (from month below)"],
            ["salary_change_from_month", "Salary change starts (YYYY-MM)"],
            ["one_time_income_amount", "One-time income amount"],
            ["one_time_income_month", "One-time income month (YYYY-MM)"],
            ["one_time_expense_amount", "One-time expense amount"],
            ["one_time_expense_month", "One-time expense month (YYYY-MM)"],
            ["additional_reservation", "One-off reservation"],
            ["reservation_due_month", "Reservation due month (YYYY-MM)"],
            ["loan_closure_amount", "Loan closure principal"],
            ["loan_closure_month", "Loan closure month (YYYY-MM)"],
          ].map(([k, label]) => (
            <View key={k}>
              <Text style={styles.label}>{label}</Text>
              <TextInput value={String(assumptions[k] ?? "")} onChangeText={(v) => setA(k, v)} style={styles.input} placeholder="—" placeholderTextColor={colors.onSurfaceTertiary} testID={`scv-${k}`} />
            </View>
          ))}
          <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={evaluate} testID="scv-run"><Text style={styles.primaryText}>{saving ? "Running…" : "Evaluate"}</Text></Pressable>

          {evalResult?.diff?.length > 0 && (
            <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
              <Text style={styles.section}>Base vs Scenario</Text>
              {evalResult.diff.map((m: any) => (
                <View key={m.month} style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle}>{monthLabel(m.month)}</Text>
                    <Text style={styles.rowMeta}>Base {scen.currency} {formatMoney(m.base_liquid)} → Scenario {scen.currency} {formatMoney(m.scenario_liquid)}</Text>
                  </View>
                  {m.scenario_shortfall && !m.base_shortfall && <Text style={styles.warn}>NEW SHORTFALL</Text>}
                  {!m.scenario_shortfall && m.base_shortfall && <Text style={styles.ok}>RESOLVED</Text>}
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
  help: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic", lineHeight: 18 },
  label: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", marginTop: spacing.lg },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "700" },
  section: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.md },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  warn: { fontSize: 11, color: colors.error, fontWeight: "700" },
  ok: { fontSize: 11, color: colors.success, fontWeight: "700" },
});
