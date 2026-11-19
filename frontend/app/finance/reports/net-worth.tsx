import { useCallback, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { StatementHeading, StatementLine, amountOf, firstBlock, labelOf, linesOf, reportMoney } from "@/src/components/finance/ReportBits";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

/** Statement of Net Worth — old side-by-side format; stacks (left first) on narrow screens. */
export default function NetWorthStatement() {
  const { width } = useWindowDimensions();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setData(firstBlock(await api.getNetWorthReport()));
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(useCallback(() => { load().finally(() => setLoading(false)); }, [load]));

  const cur = data?.currency;
  const m = (v: unknown) => reportMoney(cur, v);
  const left = data?.left ?? {};
  const nw = left.net_worth ?? {};
  const liabilities: any[] = left.liabilities ?? [];
  const assets: any[] = data?.right?.assets ?? [];
  const fyStart = data?.financial_year_start ? dateLabel(data.financial_year_start).replace(/ \d{4}$/, "") : "1 Apr";
  const sideBySide = width >= 720;

  const groupLines = (g: any, prefix: string) => (
    <View key={`${prefix}-${labelOf(g)}`}>
      <StatementLine label={labelOf(g)} amounts={[m(amountOf(g))]} bold topRule testID={`${prefix}-group-${labelOf(g)}`} />
      {linesOf(g).map((l: any, i: number) => (
        <StatementLine key={`${labelOf(l)}-${i}`} label={labelOf(l)} amounts={[m(amountOf(l))]} indent muted />
      ))}
    </View>
  );

  const leftCol = (
    <FoldCard style={sideBySide ? styles.col : undefined} testID="nw-left">
      <StatementHeading text="LIABILITIES & NET WORTH" />
      <StatementLine label="Net worth" amounts={[""]} bold topRule />
      <StatementLine label={`Opening net worth (${fyStart})`} amounts={[m(nw.opening)]} indent testID="nw-opening" />
      <StatementLine label="Add: surplus this year" amounts={[m(nw.surplus_this_year)]} indent testID="nw-surplus" />
      <StatementLine label="Other changes" amounts={[m(nw.other_changes)]} indent testID="nw-other" />
      <StatementLine label="Net worth" amounts={[m(nw.total)]} bold topRule testID="nw-total-networth" />
      {liabilities.map((g) => groupLines(g, "nw-liab"))}
      {sideBySide ? <View style={{ flex: 1 }} /> : null}
      <StatementLine label="Total" amounts={[m(left.total)]} bold doubleRule testID="nw-left-total" />
    </FoldCard>
  );

  const rightCol = (
    <FoldCard style={sideBySide ? styles.col : { marginTop: financeSpace.lg }} testID="nw-right">
      <StatementHeading text="ASSETS" />
      {assets.length === 0 ? <Text style={styles.empty}>No assets recorded yet.</Text> : assets.map((g) => groupLines(g, "nw-asset"))}
      {sideBySide ? <View style={{ flex: 1 }} /> : null}
      <StatementLine label="Total" amounts={[m(data?.right?.total)]} bold doubleRule testID="nw-right-total" />
    </FoldCard>
  );

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Net worth" subtitle="What you own and what you owe" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
        >
          {error ? <Text style={styles.error} testID="nw-error">{error}</Text> : null}
          {data ? (
            <>
              <Text style={styles.title} testID="nw-title">Statement of Net Worth as at {dateLabel(data.as_of)}</Text>
              <View style={sideBySide ? styles.row : undefined}>{leftCol}{rightCol}</View>
            </>
          ) : !error ? <Text style={styles.empty}>Nothing to show yet.</Text> : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.lg, paddingBottom: financeSpace.xxxl * 2 },
  title: { fontSize: 15, fontWeight: "700", color: financeColors.ink, marginBottom: financeSpace.md, textAlign: "center" },
  row: { flexDirection: "row", gap: financeSpace.lg, alignItems: "stretch" },
  col: { flex: 1, justifyContent: "space-between" },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.lg },
  error: { fontSize: 13, color: financeColors.negative, marginBottom: financeSpace.md },
});
