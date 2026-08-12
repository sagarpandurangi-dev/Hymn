import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldPill, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

const STATE_TONE: Record<string, "neutral" | "info" | "ok" | "err" | "warn"> = {
  draft: "neutral", reserved: "info", completed: "ok", cancelled: "neutral", expired: "err",
};
const STATE_LABEL: Record<string, string> = {
  draft: "Draft", reserved: "Reserved", completed: "Completed", cancelled: "Cancelled", expired: "Expired",
};

export default function CommitmentsList() {
  const router = useRouter();
  const { currency, state } = useLocalSearchParams<{ currency?: string; state?: string }>();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setRows(await api.listFinancialCommitments({ currency, state, include_terminal: true })); } catch { /* ignore */ }
    setLoading(false);
  }, [currency, state]);

  useEffect(() => { load(); }, [load]);

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader
        title="Commitments"
        subtitle={[currency, state].filter(Boolean).join(" · ") || undefined}
        right={
          <Pressable onPress={() => router.push("/finance/commitments/new")} hitSlop={12} testID="commitments-new" style={styles.iconBtn}>
            <Ionicons name="add" size={20} color={financeColors.ink} />
          </Pressable>
        }
      />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No commitments yet. Tap + to create one.</Text></FoldCard>
          ) : (
            <FoldCard>
              {rows.map((c, idx) => (
                <FoldRow
                  key={c.id}
                  first={idx === 0}
                  testID={`fc-row-${c.id}`}
                  onPress={() => router.push(`/finance/commitments/${c.id}`)}
                  chevron
                  label={
                    <View style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <Text style={[financeType.rowLabel, { maxWidth: 200 }]} numberOfLines={1}>{c.title}</Text>
                      <FoldPill label={STATE_LABEL[c.state] || c.state} tone={STATE_TONE[c.state] || "neutral"} size="xs" />
                      {c.is_overdue ? <FoldPill label="Overdue" tone="err" size="xs" /> : null}
                    </View>
                  }
                  meta={`Due ${dateLabel(c.due_date)}`}
                  right={<FoldAmount currency={c.currency} value={formatMoney(c.amount)} />}
                />
              ))}
            </FoldCard>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.lg, textAlign: "center", fontStyle: "italic" },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
});
