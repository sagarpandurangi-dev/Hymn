import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldHero, FoldPill, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
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

  if (loading || !e) return (
    <SafeAreaView style={foldPageStyle}>
      <FinanceHeader title="Event" />
      <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} />
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Actual event" subtitle={e.description || "(no description)"} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <FoldHero
          currency={e.currency}
          amount={`${e.direction === "outflow" ? "-" : "+"}${formatMoney(e.amount)}`}
          size="xl"
          caption={`${dateLabel(e.event_date)} · ${e.source}`}
        />
        <View style={{ flexDirection: "row", gap: 6 }}>
          <FoldPill label={e.confirmation_status} tone={e.confirmation_status === "confirmed" ? "ok" : e.confirmation_status === "rejected" ? "neutral" : "warn"} />
          <FoldPill label={e.direction} tone={e.direction === "inflow" ? "ok" : "neutral"} />
        </View>

        <FoldCard style={styles.linkGroup}>
          {e.checkin_id ? (
            <Pressable style={styles.linkRow} onPress={() => router.push(`/timeline?highlight=${e.checkin_id}`)}>
              <Ionicons name="link-outline" size={14} color={financeColors.accent} />
              <Text style={styles.linkText}>View originating check-in</Text>
              <Ionicons name="chevron-forward" size={14} color={financeColors.inkFaint} style={{ marginLeft: "auto" }} />
            </Pressable>
          ) : null}
          {e.commitment_id ? (
            <Pressable style={[styles.linkRow, styles.divider]} onPress={() => router.push(`/finance/commitments/${e.commitment_id}`)}>
              <Ionicons name="link-outline" size={14} color={financeColors.accent} />
              <Text style={styles.linkText}>View linked commitment</Text>
              <Ionicons name="chevron-forward" size={14} color={financeColors.inkFaint} style={{ marginLeft: "auto" }} />
            </Pressable>
          ) : null}
          <Pressable style={[styles.linkRow, styles.divider]} onPress={() => router.push(`/finance/audit/financial_event/${e.id}`)}>
            <Ionicons name="time-outline" size={14} color={financeColors.accent} />
            <Text style={styles.linkText}>Audit trail</Text>
            <Ionicons name="chevron-forward" size={14} color={financeColors.inkFaint} style={{ marginLeft: "auto" }} />
          </Pressable>
        </FoldCard>

        {e.source_reference ? <Text style={styles.foot}>Source ref · {e.source_reference}</Text> : null}

        {e.confirmation_status === "pending" ? (
          <View style={{ flexDirection: "row", gap: financeSpace.md }}>
            <Pressable style={styles.primary} onPress={confirm}><Text style={styles.primaryText}>Confirm</Text></Pressable>
            <Pressable style={styles.secondary} onPress={reject}><Text style={styles.secondaryText}>Reject</Text></Pressable>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  linkGroup: {},
  linkRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: financeSpace.lg, paddingVertical: 14, backgroundColor: "#FFFFFF" },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  linkText: { ...financeType.body, color: financeColors.accent, fontWeight: "600" } as any,
  foot: { fontSize: 11, color: financeColors.inkFaint, fontStyle: "italic", letterSpacing: 0.3 },
  primary: { flex: 1, backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center" },
  primaryText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { flex: 1, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  secondaryText: { color: financeColors.ink, fontSize: 13, fontWeight: "600" },
});
