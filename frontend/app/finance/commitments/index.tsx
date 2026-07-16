import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { dateLabel, formatMoney, stateColor, stateLabel } from "@/src/lib/finance/format";

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
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Financial Commitments" subtitle={[currency, state].filter(Boolean).join(" · ")} right={<Pressable onPress={() => router.push("/finance/commitments/new")} hitSlop={12} testID="commitments-new"><Ionicons name="add" size={22} color={colors.onSurface} /></Pressable>} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 && <Text style={styles.empty}>No commitments yet. Tap + to create one.</Text>}
          {rows.map((c) => (
            <Pressable key={c.id} style={styles.row} onPress={() => router.push(`/finance/commitments/${c.id}`)} testID={`fc-row-${c.id}`}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                  <Text style={styles.title} numberOfLines={1}>{c.title}</Text>
                  <View style={[styles.chip, { backgroundColor: stateColor(c.state) }]}>
                    <Text style={styles.chipText}>{stateLabel(c.state)}</Text>
                  </View>
                </View>
                <Text style={styles.meta}>{c.currency} {formatMoney(c.amount)} · due {dateLabel(c.due_date)}{c.is_overdue ? " · overdue" : ""}</Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.xl, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  title: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  meta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  chip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill },
  chipText: { fontSize: 10, color: "#fff", fontWeight: "700", letterSpacing: 0.5 },
});
