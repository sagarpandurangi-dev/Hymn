import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function ReconciliationScreen() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setItems(await api.reconciliationSuggestions()); } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const confirm = async (eventId: string, commitmentId: string) => {
    setBusy(true); try { await api.reconcileConfirm(eventId, { commitment_id: commitmentId }); await load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } finally { setBusy(false); }
  };
  const reject = async (eventId: string) => {
    setBusy(true); try { await api.reconcileReject(eventId); await load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Reconciliation" subtitle="Match confirmed events to commitments" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {items.length === 0 ? (
            <FoldCard><Text style={styles.empty}>Nothing to reconcile right now.</Text></FoldCard>
          ) : (
            items.map((it) => (
              <FoldCard key={it.event.id} style={styles.card}>
                <View style={styles.head}>
                  <Text style={styles.title} numberOfLines={2}>{it.event.description || "(no description)"}</Text>
                  <FoldAmount currency={it.event.currency} value={formatMoney(it.event.amount)} size="md" />
                </View>
                <Text style={styles.meta}>{dateLabel(it.event.event_date)} · {it.event.source}</Text>

                {it.single_strong_match ? (
                  <>
                    <Text style={styles.body}>Possible match with “{it.single_strong_match.commitment.title}”.</Text>
                    <Text style={styles.hint}>Confirming completes the commitment, records the actual amount, releases unused reservation and recalculates forecasts.</Text>
                    <View style={styles.actions}>
                      <Pressable style={styles.primary} disabled={busy} onPress={() => confirm(it.event.id, it.single_strong_match.commitment.id)} testID={`recon-confirm-${it.event.id}`}>
                        <Text style={styles.primaryText}>Confirm match</Text>
                      </Pressable>
                      <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-reject-${it.event.id}`}>
                        <Text style={styles.secondaryText}>Reject</Text>
                      </Pressable>
                    </View>
                  </>
                ) : it.matches.length > 0 ? (
                  <>
                    <Text style={styles.body}>Multiple possible matches. Select one, or reject.</Text>
                    <View style={styles.matchList}>
                      {it.matches.map((m: any, idx: number) => (
                        <Pressable
                          key={m.commitment.id}
                          style={[styles.matchRow, idx > 0 && styles.rowDivider]}
                          disabled={busy}
                          onPress={() => confirm(it.event.id, m.commitment.id)}
                          testID={`recon-pick-${it.event.id}-${m.commitment.id}`}
                        >
                          <View style={{ flex: 1 }}>
                            <Text style={styles.mTitle}>{m.commitment.title}</Text>
                            <Text style={styles.mMeta}>Due {dateLabel(m.commitment.due_date)} · {m.commitment.priority} · score {m.score}</Text>
                          </View>
                          <FoldAmount currency={m.commitment.currency} value={formatMoney(m.commitment.amount)} />
                        </Pressable>
                      ))}
                    </View>
                    <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-none-${it.event.id}`}>
                      <Text style={styles.secondaryText}>None of these</Text>
                    </Pressable>
                  </>
                ) : (
                  <>
                    <Text style={styles.body}>No suitable match. Treat as unplanned?</Text>
                    <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-unplanned-${it.event.id}`}>
                      <Text style={styles.secondaryText}>Yes, unplanned</Text>
                    </Pressable>
                  </>
                )}
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
  card: { padding: financeSpace.lg, gap: 4 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: financeSpace.md },
  title: { ...financeType.rowLabel, fontSize: 15, fontWeight: "700", flex: 1 } as any,
  meta: { fontSize: 12, color: financeColors.inkMuted },
  body: { ...financeType.body, marginTop: financeSpace.sm } as any,
  hint: { fontSize: 12, color: financeColors.inkMuted, lineHeight: 17, marginTop: 2 },
  actions: { flexDirection: "row", gap: financeSpace.sm, marginTop: financeSpace.md },
  primary: { flex: 1, backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center" },
  primaryText: { color: "#FBFBF6", fontSize: 12.5, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { flex: 1, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", marginTop: financeSpace.sm },
  secondaryText: { color: financeColors.ink, fontSize: 12.5, fontWeight: "600", letterSpacing: 0.3 },
  matchList: { marginTop: financeSpace.sm, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, borderRadius: financeRadius.sm, overflow: "hidden" },
  matchRow: { flexDirection: "row", alignItems: "center", gap: financeSpace.md, padding: financeSpace.md, backgroundColor: "#FFFFFF" },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  mTitle: { fontSize: 13, color: financeColors.ink, fontWeight: "600" },
  mMeta: { fontSize: 11, color: financeColors.inkMuted, marginTop: 2 },
});
