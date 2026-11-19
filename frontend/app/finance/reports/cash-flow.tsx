import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import MonthPickerField from "@/src/components/finance/MonthPickerField";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { StatementHeading, StatementLine, amountOf, firstBlock, labelOf, linesOf, reportMoney } from "@/src/components/finance/ReportBits";
import { currentMonthIso, dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const SECTION_LABELS: Record<string, string> = { living: "Living", investing: "Investing", borrowing: "Borrowing", other: "Other" };

export default function CashFlow() {
  const [month, setMonth] = useState(currentMonthIso());
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const reqId = useRef(0);
  const load = useCallback(async (mo: string) => {
    const id = ++reqId.current; // ignore a slower answer for a month no longer picked
    setError("");
    try {
      const res = firstBlock(await api.getCashFlowReport(mo));
      if (id === reqId.current) setData(res);
    } catch (e) {
      if (id === reqId.current) setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(month).finally(() => setLoading(false)); }, [load, month]));

  const m = (v: unknown) => reportMoney(data?.currency, v);
  const sections: any[] = data?.sections ?? [];
  const sectionName = (s: any) => SECTION_LABELS[String(s?.key ?? s?.section ?? "").toLowerCase()] ?? labelOf(s);

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Cash flow" subtitle={data?.start ? `${dateLabel(data.start)} – ${dateLabel(data.end)}` : "Money in and out of your cash"} />
      <View style={styles.picker}>
        <MonthPickerField value={month} onChange={(v) => { if (v) { setLoading(true); setMonth(v); } }} testID="cf-month" />
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(month); setRefreshing(false); }} />}
        >
          {error ? <Text style={styles.error} testID="cf-error">{error}</Text> : null}
          {data ? (
            <>
              <FoldCard testID="cf-card">
                <StatementLine label="Opening cash" amounts={[m(data.opening_cash)]} bold testID="cf-opening" />
                {sections.map((s, i) => (
                  <View key={`${sectionName(s)}-${i}`} testID={`cf-section-${sectionName(s)}`}>
                    <StatementHeading text={sectionName(s).toUpperCase()} />
                    {linesOf(s).map((l: any, j: number) => (
                      <StatementLine key={`${labelOf(l)}-${j}`} label={labelOf(l)} amounts={[m(amountOf(l))]} indent muted />
                    ))}
                    <StatementLine label={`Net ${sectionName(s).toLowerCase()}`} amounts={[m(s?.net ?? amountOf(s))]} bold topRule />
                  </View>
                ))}
                <StatementLine label="Net change" amounts={[m(data.net_change)]} bold topRule testID="cf-net-change" />
                <StatementLine label="Closing cash" amounts={[m(data.closing_cash)]} bold doubleRule testID="cf-closing" />
              </FoldCard>
              {data.adds_up ? (
                <View style={styles.ok} testID="cf-adds-up">
                  <Ionicons name="checkmark-circle" size={14} color={financeColors.positive} />
                  <Text style={styles.okText}>Adds up</Text>
                </View>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  picker: { paddingHorizontal: financeSpace.lg, paddingBottom: financeSpace.sm },
  scroll: { padding: financeSpace.lg, paddingTop: 0, paddingBottom: financeSpace.xxxl * 2 },
  error: { fontSize: 13, color: financeColors.negative, marginBottom: financeSpace.md },
  ok: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: financeSpace.md, alignSelf: "flex-end" },
  okText: { fontSize: 12, fontWeight: "700", color: financeColors.positive },
});
