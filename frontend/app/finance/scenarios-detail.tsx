import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldPill, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
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

  if (loading || !scen) return (
    <SafeAreaView style={foldPageStyle}>
      <FinanceHeader title="Scenario" />
      <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} />
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={scen.name} subtitle={`Sandbox · ${scen.currency}`} />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.help}>Enter one or more levers. Nothing here changes your real Portfolio, Tasks, Check-ins or Commitments.</Text>

          <FoldSectionHeader label="Assumptions" />
          <FoldCard style={{ padding: financeSpace.lg, gap: financeSpace.sm }}>
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
                <Text style={styles.label}>{String(label).toUpperCase()}</Text>
                <TextInput value={String(assumptions[k] ?? "")} onChangeText={(v) => setA(k, v)} style={styles.input} placeholder="—" placeholderTextColor={financeColors.inkFaint} testID={`scv-${k}`} />
              </View>
            ))}
          </FoldCard>

          <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={evaluate} testID="scv-run">
            <Text style={styles.primaryText}>{saving ? "Running…" : "Evaluate"}</Text>
          </Pressable>

          {evalResult?.diff?.length > 0 ? (
            <View>
              <FoldSectionHeader label="Base vs scenario" />
              <FoldCard>
                {evalResult.diff.map((m: any, idx: number) => (
                  <FoldRow
                    key={m.month}
                    first={idx === 0}
                    label={monthLabel(m.month)}
                    meta={`Base ${scen.currency} ${formatMoney(m.base_liquid)}`}
                    right={
                      <View style={{ alignItems: "flex-end", gap: 4 }}>
                        <FoldAmount currency={scen.currency} value={formatMoney(m.scenario_liquid)} tone={m.scenario_shortfall && !m.base_shortfall ? "negative" : "ink"} />
                        {m.scenario_shortfall && !m.base_shortfall ? <FoldPill label="New shortfall" tone="err" size="xs" /> : null}
                        {!m.scenario_shortfall && m.base_shortfall ? <FoldPill label="Resolved" tone="ok" size="xs" /> : null}
                      </View>
                    }
                  />
                ))}
              </FoldCard>
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  help: { fontSize: 12, color: financeColors.inkMuted, fontStyle: "italic", lineHeight: 17, paddingHorizontal: 2 },
  label: { ...financeType.sectionLabel, marginTop: financeSpace.sm } as any,
  input: { backgroundColor: "#FBFBF6", borderRadius: financeRadius.sm, paddingHorizontal: financeSpace.md, paddingVertical: financeSpace.md, fontSize: 15, color: financeColors.ink, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, marginTop: 4 },
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center", marginTop: financeSpace.sm },
  primaryText: { color: "#FBFBF6", fontSize: 13.5, fontWeight: "700", letterSpacing: 0.4 },
});
