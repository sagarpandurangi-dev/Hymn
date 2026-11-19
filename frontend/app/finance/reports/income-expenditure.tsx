import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import MonthPickerField from "@/src/components/finance/MonthPickerField";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { StatementHeading, StatementLine, amountOf, firstBlock, labelOf, linesOf, reportMoney } from "@/src/components/finance/ReportBits";
import { currentMonthIso } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const PERIODS = ["this_month", "last_month", "year_to_date"] as const;
const COLS = ["This month", "Last month", "Year to date"];

const catKey = (c: any) => String(c?.category ?? c?.key ?? labelOf(c));

/** Union of group/category labels across the three periods, in first-seen order. */
function mergeGroups(data: any, side: "income" | "expenditure") {
  const order: string[] = [];
  const byPeriod = PERIODS.map((p) => {
    const map = new Map<string, any>();
    (data?.[p]?.[side] ?? []).forEach((g: any) => {
      const k = labelOf(g);
      map.set(k, g);
      if (!order.includes(k)) order.push(k);
    });
    return map;
  });
  return order.map((label) => {
    const groups = byPeriod.map((m) => m.get(label));
    const catOrder: string[] = [];
    const catLabels: Record<string, string> = {};
    groups.forEach((g) => linesOf(g).forEach((c: any) => {
      const k = catKey(c);
      if (!catOrder.includes(k)) { catOrder.push(k); catLabels[k] = labelOf(c) || k; }
    }));
    const cats = catOrder.map((k) => ({
      key: k,
      label: catLabels[k],
      amounts: groups.map((g) => amountOf(linesOf(g).find((c: any) => catKey(c) === k))),
    }));
    return { label, amounts: groups.map((g) => amountOf(g)), cats };
  });
}

export default function IncomeExpenditure() {
  const router = useRouter();
  const [month, setMonth] = useState(currentMonthIso());
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const reqId = useRef(0);
  const load = useCallback(async (m: string) => {
    const id = ++reqId.current; // ignore a slower answer for a month no longer picked
    setError("");
    try {
      const res = firstBlock(await api.getIncomeExpenditureReport(m));
      if (id === reqId.current) setData(res);
    } catch (e) {
      if (id === reqId.current) setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(month).finally(() => setLoading(false)); }, [load, month]));

  const cur = data?.currency;
  const m = (v: unknown) => reportMoney(cur, v);
  const per = (field: string) => PERIODS.map((p) => data?.[p]?.[field]);
  const rate = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : `${Number(v).toFixed(1).replace(/\.0$/, "")}%`);
  const surplus = (v: unknown) => m(v);

  const openEntries = (category: string, label: string) => {
    const tm = data?.this_month;
    if (!tm) return;
    router.push(`/finance/reports/entries?category=${encodeURIComponent(category)}&label=${encodeURIComponent(label)}&start=${tm.start}&end=${tm.end}&currency=${cur || "INR"}` as any);
  };

  const section = (side: "income" | "expenditure", title: string, totalLabel: string, totalField: string) => {
    const groups = mergeGroups(data, side);
    return (
      <>
        <StatementHeading text={title} columns={COLS} />
        {groups.length === 0 ? <Text style={styles.empty}>Nothing recorded.</Text> : null}
        {groups.map((g) => {
          const k = `${side}:${g.label}`;
          return (
            <View key={k}>
              <StatementLine
                label={g.label}
                amounts={g.amounts.map(m)}
                topRule
                onPress={g.cats.length ? () => setOpen({ ...open, [k]: !open[k] }) : undefined}
                expanded={!!open[k]}
                testID={`ie-group-${side}-${g.label}`}
              />
              {open[k] ? g.cats.map((c) => (
                <StatementLine
                  key={c.key}
                  label={c.label}
                  amounts={c.amounts.map(m)}
                  indent
                  muted
                  onPress={() => openEntries(c.key, c.label)}
                  testID={`ie-cat-${side}-${c.key}`}
                />
              )) : null}
            </View>
          );
        })}
        <StatementLine label={totalLabel} amounts={per(totalField).map(m)} bold topRule testID={`ie-${totalField}`} />
      </>
    );
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Income & Expenditure" subtitle="Where money came from and went" />
      <View style={styles.picker}>
        <MonthPickerField value={month} onChange={(v) => { if (v) { setLoading(true); setOpen({}); setMonth(v); } }} testID="ie-month" />
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(month); setRefreshing(false); }} />}
        >
          {error ? <Text style={styles.error} testID="ie-error">{error}</Text> : null}
          {data ? (
            <FoldCard testID="ie-card">
              {section("income", "INCOME", "Total income", "total_income")}
              {section("expenditure", "EXPENDITURE", "Total expenditure", "total_expenditure")}
              <StatementLine label="SURPLUS / (DEFICIT)" amounts={per("surplus").map(surplus)} bold doubleRule testID="ie-surplus" />
              <StatementLine label="Savings rate" amounts={per("savings_rate_percent").map(rate)} muted testID="ie-savings-rate" />
            </FoldCard>
          ) : null}
          <Text style={styles.hint}>Tap a group to see its categories, and a category to see its entries for this month.</Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  picker: { paddingHorizontal: financeSpace.lg, paddingBottom: financeSpace.sm },
  scroll: { padding: financeSpace.lg, paddingTop: 0, paddingBottom: financeSpace.xxxl * 2 },
  empty: { fontSize: 13, color: financeColors.inkMuted, paddingHorizontal: financeSpace.lg, paddingBottom: financeSpace.sm },
  error: { fontSize: 13, color: financeColors.negative, marginBottom: financeSpace.md },
  hint: { fontSize: 12, color: financeColors.inkMuted, marginTop: financeSpace.md },
});
