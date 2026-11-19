import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { lifeStyles as s } from "@/src/components/finance/lifeObjects";
import { ASSET_GROUPS, LIABILITY_GROUPS, relationLabel } from "@/src/lib/family";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const LABEL_W = 120;
const COL_W = 118;

export default function FamilyNetWorthScreen() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    api.getFamilyNetWorth().then(setData).catch((e: ApiError) => setError(e.message || "Couldn't load the family net worth."));
  }, []));

  const cur = data?.currency ?? "INR";
  const members: any[] = data?.members ?? [];
  const family = data?.family ?? {};
  const cols = [
    ...members.map((m) => ({ key: m.member_id ?? m.name, title: m.name, sub: relationLabel(m.relation), d: m, full: m.share === "full" })),
    { key: "family", title: "Family", sub: "Total", d: family, full: true },
  ];
  const m = (v: any) => reportMoney(cur, v ?? 0);
  const cell = (c: (typeof cols)[number], fn: (d: any) => any) => (c.full ? m(fn(c.d)) : "—");

  const rows: { label: string; get: (c: (typeof cols)[number]) => string; bold?: boolean; head?: boolean; indent?: boolean }[] = [
    { label: "Net worth", get: (c) => m(c.d.net_worth), bold: true },
    { label: "ASSETS", get: () => "", head: true },
    ...ASSET_GROUPS.map((g) => ({ label: g.label.replace(/ \(.*\)$/, ""), get: (c: any) => cell(c, (d) => d.assets?.[g.code]), indent: true })),
    { label: "Total assets", get: (c) => cell(c, (d) => d.total_assets), bold: true },
    { label: "LIABILITIES", get: () => "", head: true },
    ...LIABILITY_GROUPS.map((g) => ({ label: g.label.replace(/ \(.*\)$/, ""), get: (c: any) => cell(c, (d) => d.liabilities?.[g.code]), indent: true })),
    { label: "Total liabilities", get: (c) => cell(c, (d) => d.total_liabilities), bold: true },
  ];

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]} testID="family-net-worth">
      <FinanceHeader title="Family net worth" subtitle={data?.as_of ? `As of ${dateLabel(data.as_of)}` : undefined} />
      <ScrollView contentContainerStyle={s.scroll}>
        {!data ? (
          error ? <Text style={s.error} testID="family-nw-error">{error}</Text> : <ActivityIndicator color={financeColors.inkMuted} />
        ) : (
          <>
            <FoldCard>
              <View style={s.pad}>
                <Text style={s.body}>Family net worth</Text>
                <Text style={{ fontSize: 28, fontWeight: "700", color: financeColors.ink }} testID="family-nw-total">{m(family.net_worth)}</Text>
              </View>
            </FoldCard>
            {cols.length > 2 ? <Text style={s.body}>Swipe the table sideways to see everyone and the family total.</Text> : null}
            <FoldCard testID="family-nw-table">
              <View style={{ flexDirection: "row" }}>
                <View style={{ width: LABEL_W }}>
                  <View style={[st.head, st.cellPad]} />
                  {rows.map((r, i) => (
                    <View key={i} style={[st.cellPad, st.rowH, i > 0 && st.rule]}>
                      <Text style={[st.label, r.bold && st.bold, r.head && st.headText, r.indent && { paddingLeft: 8 }]} numberOfLines={1}>{r.label}</Text>
                    </View>
                  ))}
                </View>
                <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                  {cols.map((c) => (
                    <View key={c.key} style={[{ width: COL_W }, c.key === "family" && st.familyCol]} testID={`family-nw-col-${c.key}`}>
                      <View style={[st.head, st.cellPad]}>
                        <Text style={[st.colTitle]} numberOfLines={1}>{c.title}</Text>
                        <Text style={st.colSub} numberOfLines={1}>{c.full ? c.sub : `${c.sub} · total only`}</Text>
                      </View>
                      {rows.map((r, i) => (
                        <View key={i} style={[st.cellPad, st.rowH, i > 0 && st.rule]}>
                          <Text style={[st.num, r.bold && st.bold]} numberOfLines={1} adjustsFontSizeToFit>{r.get(c)}</Text>
                        </View>
                      ))}
                    </View>
                  ))}
                </ScrollView>
              </View>
            </FoldCard>
            <Text style={s.body} testID="family-nw-note">Joint things are counted once.</Text>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  cellPad: { paddingHorizontal: financeSpace.sm, justifyContent: "center" },
  rowH: { height: 40 },
  head: { height: 52, backgroundColor: financeColors.page },
  rule: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  label: { fontSize: 13, color: financeColors.ink },
  headText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.8, color: financeColors.inkMuted },
  bold: { fontWeight: "700" },
  num: { fontSize: 13, color: financeColors.ink, textAlign: "right", fontVariant: ["tabular-nums"] },
  colTitle: { fontSize: 13, fontWeight: "700", color: financeColors.ink, textAlign: "right" },
  colSub: { fontSize: 11, color: financeColors.inkMuted, textAlign: "right" },
  familyCol: { backgroundColor: financeColors.pillInfoBg },
});
