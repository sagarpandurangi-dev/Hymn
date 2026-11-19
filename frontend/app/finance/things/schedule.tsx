import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { lifeStyles as s, PremiumCard } from "@/src/components/finance/lifeObjects";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

export default function LoanScheduleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [premium, setPremium] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getLifeObjectSchedule(String(id)).then(setData).catch((e: ApiError) => {
      if (e.status === 403) setPremium(false);
      else setError(e.message || "Couldn't load the schedule.");
    });
  }, [id]);

  const cur = data?.currency ?? "INR";
  const rows: any[] = data?.rows ?? data?.schedule ?? [];
  const m = (v: any) => reportMoney(cur, v ?? 0);

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Loan schedule" />
      <ScrollView contentContainerStyle={s.scroll}>
        {!premium ? <PremiumCard text="Loan schedules are part of Premium." /> : !data ? (
          error ? <Text style={s.error}>{error}</Text> : <ActivityIndicator color={financeColors.inkMuted} />
        ) : (
          <>
            <FoldCard>
              <FoldRow first label="EMI" right={m(data.emi)} testID="schedule-emi" />
              <FoldRow label="Total interest" right={m(data.total_interest)} testID="schedule-total-interest" />
            </FoldCard>
            <FoldCard testID="schedule-table">
              <View style={[st.row, st.head]}>
                <Text style={[st.c0, st.h]}>#</Text>
                <Text style={[st.c1, st.h]}>Date</Text>
                <Text style={[st.c, st.h]}>Principal</Text>
                <Text style={[st.c, st.h]}>Interest</Text>
                <Text style={[st.c, st.h]}>Left</Text>
              </View>
              {rows.map((r, i) => (
                <View key={i} style={[st.row, i > 0 && st.rule]} testID={`schedule-row-${i}`}>
                  <Text style={st.c0}>{r.n ?? r.number ?? r.month ?? i + 1}</Text>
                  <Text style={st.c1}>{r.date ? dateLabel(String(r.date).slice(0, 10)) : ""}</Text>
                  <Text style={st.c} numberOfLines={1} adjustsFontSizeToFit>{m(r.principal)}</Text>
                  <Text style={st.c} numberOfLines={1} adjustsFontSizeToFit>{m(r.interest)}</Text>
                  <Text style={st.c} numberOfLines={1} adjustsFontSizeToFit>{m(r.balance ?? r.outstanding ?? r.closing_balance)}</Text>
                </View>
              ))}
            </FoldCard>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", paddingHorizontal: financeSpace.md, paddingVertical: 10, gap: 6 },
  head: { backgroundColor: financeColors.page },
  rule: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  h: { fontWeight: "700", color: financeColors.inkMuted, fontSize: 11 },
  c0: { width: 24, fontSize: 12, color: financeColors.inkMuted },
  c1: { width: 72, fontSize: 12, color: financeColors.ink },
  c: { flex: 1, fontSize: 12, color: financeColors.ink, textAlign: "right", fontVariant: ["tabular-nums"] },
});
