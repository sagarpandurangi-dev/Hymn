import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Actual events" subtitle={`${rows.length} recorded`} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {dedupe.length > 0 && (
            <View>
              <FoldSectionHeader label={`${dedupe.length} possible duplicate${dedupe.length === 1 ? "" : "s"}`} hint="Review before they count twice" />
              <FoldCard>
                {dedupe.map((d, idx) => (
                  <View key={d.id} style={[styles.dedupeCard, idx > 0 && styles.rowDivider]}>
                    {d.event_a && d.event_b ? (
                      <>
                        <Text style={styles.dedupeRow}>A · {d.event_a.description || "(no description)"} · {d.event_a.currency} {formatMoney(d.event_a.amount)}</Text>
                        <Text style={styles.dedupeRow}>B · {d.event_b.description || "(no description)"} · {d.event_b.currency} {formatMoney(d.event_b.amount)}</Text>
                      </>
                    ) : null}
                    <View style={styles.dedupeActions}>
                      <Pressable style={styles.smallBtn} onPress={async () => { await api.resolveDedupe(d.id, "same", d.event_a_id); load(); }} testID={`dedupe-same-${d.id}`}>
                        <Text style={styles.smallBtnText}>Same</Text>
                      </Pressable>
                      <Pressable style={styles.smallBtnGhost} onPress={async () => { await api.resolveDedupe(d.id, "different"); load(); }} testID={`dedupe-diff-${d.id}`}>
                        <Text style={styles.smallBtnGhostText}>Different</Text>
                      </Pressable>
                    </View>
                  </View>
                ))}
              </FoldCard>
            </View>
          )}

          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No events yet. Check-ins with money spent, imports and manual entries appear here.</Text></FoldCard>
          ) : (
            <FoldCard>
              {rows.map((e, idx) => (
                <FoldRow
                  key={e.id}
                  first={idx === 0}
                  onPress={() => router.push(`/finance/events/${e.id}`)}
                  testID={`ev-row-${e.id}`}
                  chevron
                  label={e.description || "(no description)"}
                  meta={`${dateLabel(e.event_date)} · ${e.source} · ${e.confirmation_status}`}
                  right={
                    <FoldAmount
                      currency={e.currency}
                      value={formatMoney(e.amount)}
                      sign={e.direction === "outflow" ? "-" : "+"}
                      tone={e.direction === "inflow" ? "positive" : "ink"}
                    />
                  }
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
  dedupeCard: { padding: financeSpace.lg, gap: 4 },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  dedupeRow: { ...financeType.body, fontSize: 12.5 } as any,
  dedupeActions: { flexDirection: "row", gap: financeSpace.sm, marginTop: financeSpace.sm },
  smallBtn: { paddingHorizontal: financeSpace.md, paddingVertical: 6, borderRadius: financeRadius.pill, backgroundColor: financeColors.ink },
  smallBtnText: { color: "#FBFBF6", fontSize: 11.5, fontWeight: "700", letterSpacing: 0.4 },
  smallBtnGhost: { paddingHorizontal: financeSpace.md, paddingVertical: 6, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  smallBtnGhostText: { color: financeColors.ink, fontSize: 11.5, fontWeight: "700", letterSpacing: 0.4 },
});
