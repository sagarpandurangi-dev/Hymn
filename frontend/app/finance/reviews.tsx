import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
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
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Reviews" subtitle="Every 15 days for Reserved commitments" />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 && <Text style={styles.empty}>Nothing due right now.</Text>}
          {rows.map((c) => (
            <View key={c.id} style={styles.card}>
              <Text style={styles.title}>{c.title}</Text>
              <Text style={styles.meta}>{c.currency} {formatMoney(c.amount)} · due {dateLabel(c.due_date)}</Text>
              <Text style={styles.body}>Is this Financial Commitment still expected to happen?</Text>
              <View style={styles.actions}>
                <Pressable style={styles.primary} onPress={() => keep(c.id)} testID={`rv-keep-${c.id}`}><Text style={styles.primaryText}>Yes, keep reserved</Text></Pressable>
                <Pressable style={styles.secondary} onPress={() => router.push(`/finance/commitments/${c.id}`)} testID={`rv-open-${c.id}`}><Text style={styles.secondaryText}>Complete / Cancel / Postpone</Text></Pressable>
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.xl, textAlign: "center" },
  card: { padding: spacing.lg, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, gap: spacing.xs },
  title: { fontSize: 15, color: colors.onSurface, fontWeight: "700" },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary },
  body: { fontSize: 13, color: colors.onSurface, marginTop: spacing.sm },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 13, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  secondaryText: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
});
