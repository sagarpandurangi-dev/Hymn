import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function EventsList() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [dedupe, setDedupe] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ev, dc] = await Promise.all([
        api.listFinancialEvents({ limit: 100 }),
        api.listDedupeCandidates().catch(() => []),
      ]);
      setRows(ev);
      setDedupe(dc || []);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Actual Financial Events" subtitle={`${rows.length} recorded`} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {dedupe.length > 0 && (
            <View style={styles.dedupeBanner}>
              <Text style={styles.dedupeTitle}>{dedupe.length} possible duplicate{dedupe.length === 1 ? "" : "s"} awaiting your review</Text>
              {dedupe.map((d) => (
                <View key={d.id} style={styles.dedupeCard}>
                  {d.event_a && d.event_b ? (
                    <>
                      <Text style={styles.dedupeRow}>A: {d.event_a.description || "(no description)"} · {d.event_a.currency} {formatMoney(d.event_a.amount)} · {d.event_a.source}</Text>
                      <Text style={styles.dedupeRow}>B: {d.event_b.description || "(no description)"} · {d.event_b.currency} {formatMoney(d.event_b.amount)} · {d.event_b.source}</Text>
                    </>
                  ) : null}
                  <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                    <Pressable style={styles.smallBtn} onPress={async () => { await api.resolveDedupe(d.id, "same", d.event_a_id); load(); }} testID={`dedupe-same-${d.id}`}><Text style={styles.smallBtnText}>Same</Text></Pressable>
                    <Pressable style={styles.smallBtn} onPress={async () => { await api.resolveDedupe(d.id, "different"); load(); }} testID={`dedupe-diff-${d.id}`}><Text style={styles.smallBtnText}>Different</Text></Pressable>
                  </View>
                </View>
              ))}
            </View>
          )}
          {rows.length === 0 && <Text style={styles.empty}>No events yet. Check-ins with money spent, imports and manual entries appear here.</Text>}
          {rows.map((e) => (
            <Pressable key={e.id} style={styles.row} onPress={() => router.push(`/finance/events/${e.id}`)} testID={`ev-row-${e.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title} numberOfLines={1}>{e.description || "(no description)"}</Text>
                <Text style={styles.meta}>{dateLabel(e.event_date)} · {e.source} · {e.direction} · {e.confirmation_status}</Text>
              </View>
              <Text style={styles.amount}>{e.direction === "outflow" ? "-" : "+"}{e.currency} {formatMoney(e.amount)}</Text>
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
  title: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  meta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  amount: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  dedupeBanner: { padding: spacing.md, backgroundColor: colors.brandTertiary, borderRadius: radius.md, gap: spacing.sm },
  dedupeTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "700" },
  dedupeCard: { padding: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.sm, gap: 4 },
  dedupeRow: { fontSize: 11, color: colors.onSurface },
  smallBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.onSurface },
  smallBtnText: { color: colors.onSurfaceInverse, fontSize: 12, fontWeight: "700" },
});
