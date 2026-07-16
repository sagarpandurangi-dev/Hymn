import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function EventDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [e, setE] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const all = await api.listFinancialEvents({ limit: 500 });
      setE(all.find((x: any) => x.id === id) || null);
    } catch { /* ignore */ }
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const confirm = async () => { try { await api.confirmFinancialEvent(id); load(); } catch (err: any) { Alert.alert("Error", err?.message || ""); } };
  const reject = async () => { try { await api.rejectFinancialEvent(id); load(); } catch (err: any) { Alert.alert("Error", err?.message || ""); } };

  if (loading || !e) return (<SafeAreaView style={styles.safe}><FinanceHeader title="Event" /><ActivityIndicator style={{ marginTop: spacing.xxxl }} /></SafeAreaView>);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Actual Financial Event" subtitle={e.description || "(no description)"} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.big}>{e.direction === "outflow" ? "-" : "+"}{e.currency} {formatMoney(e.amount)}</Text>
        <Text style={styles.meta}>{dateLabel(e.event_date)} · {e.source} · {e.confirmation_status}</Text>
        {e.checkin_id && <Pressable style={styles.link} onPress={() => router.push(`/timeline?highlight=${e.checkin_id}`)}><Text style={styles.linkText}>View originating check-in</Text></Pressable>}
        {e.commitment_id && <Pressable style={styles.link} onPress={() => router.push(`/finance/commitments/${e.commitment_id}`)}><Text style={styles.linkText}>View linked Financial Commitment</Text></Pressable>}
        {e.source_reference ? <Text style={styles.foot}>Source ref: {e.source_reference}</Text> : null}
        {e.confirmation_status === "pending" && (
          <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.md }}>
            <Pressable style={styles.primary} onPress={confirm}><Text style={styles.primaryText}>Confirm</Text></Pressable>
            <Pressable style={styles.secondary} onPress={reject}><Text style={styles.secondaryText}>Reject</Text></Pressable>
          </View>
        )}
        <Pressable style={styles.link} onPress={() => router.push(`/finance/audit/financial_event/${e.id}`)}><Text style={styles.linkText}>Audit trail</Text></Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  big: { fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  meta: { fontSize: 13, color: colors.onSurfaceSecondary },
  link: { padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm },
  linkText: { fontSize: 13, color: colors.brandPrimary, fontWeight: "600" },
  foot: { fontSize: 11, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  primary: { flex: 1, backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700" },
  secondary: { flex: 1, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", borderWidth: 1, borderColor: colors.border },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
});
