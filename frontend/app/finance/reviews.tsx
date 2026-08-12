import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function ReviewsScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setRows(await api.getCommitmentsDueForReview()); } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const keep = async (id: string) => {
    try { await api.reviewFinancialCommitment(id, { decision: "keep" }); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); }
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Reviews" subtitle="Every 15 days · reserved commitments" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>Nothing due right now.</Text></FoldCard>
          ) : (
            rows.map((c) => (
              <FoldCard key={c.id} style={styles.card}>
                <View style={styles.head}>
                  <Text style={styles.title} numberOfLines={2}>{c.title}</Text>
                  <FoldAmount currency={c.currency} value={formatMoney(c.amount)} size="md" />
                </View>
                <Text style={styles.meta}>Due {dateLabel(c.due_date)}</Text>
                <Text style={styles.body}>Is this financial commitment still expected to happen?</Text>
                <View style={styles.actions}>
                  <Pressable style={styles.primary} onPress={() => keep(c.id)} testID={`rv-keep-${c.id}`}>
                    <Text style={styles.primaryText}>Keep reserved</Text>
                  </Pressable>
                  <Pressable style={styles.secondary} onPress={() => router.push(`/finance/commitments/${c.id}`)} testID={`rv-open-${c.id}`}>
                    <Text style={styles.secondaryText}>Complete / Cancel / Postpone</Text>
                  </Pressable>
                </View>
              </FoldCard>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  card: { padding: financeSpace.lg, gap: financeSpace.xs },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: financeSpace.md },
  title: { ...financeType.rowLabel, fontSize: 15, fontWeight: "700", flex: 1 } as any,
  meta: { fontSize: 12, color: financeColors.inkMuted, marginTop: 2 },
  body: { ...financeType.body, marginTop: financeSpace.sm } as any,
  actions: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm, marginTop: financeSpace.md },
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill },
  primaryText: { color: "#FBFBF6", fontSize: 12.5, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  secondaryText: { color: financeColors.ink, fontSize: 12.5, fontWeight: "600", letterSpacing: 0.3 },
});
