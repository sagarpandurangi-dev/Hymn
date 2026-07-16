import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function ReconciliationScreen() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => { setLoading(true); try { setItems(await api.reconciliationSuggestions()); } catch { /* ignore */ } setLoading(false); }, []);
  useEffect(() => { load(); }, [load]);

  const confirm = async (eventId: string, commitmentId: string) => {
    setBusy(true); try { await api.reconcileConfirm(eventId, { commitment_id: commitmentId }); await load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } finally { setBusy(false); }
  };
  const reject = async (eventId: string) => {
    setBusy(true); try { await api.reconcileReject(eventId); await load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Reconciliation" subtitle="Match confirmed events to commitments" />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {items.length === 0 && <Text style={styles.empty}>Nothing to reconcile right now.</Text>}
          {items.map((it) => (
            <View key={it.event.id} style={styles.card}>
              <Text style={styles.title}>{it.event.description || "(no description)"}</Text>
              <Text style={styles.meta}>{it.event.currency} {formatMoney(it.event.amount)} · {dateLabel(it.event.event_date)} · {it.event.source}</Text>
              {it.single_strong_match ? (
                <>
                  <Text style={styles.body}>We found a possible match with your Financial Commitment “{it.single_strong_match.commitment.title}”.</Text>
                  <Text style={styles.body}>Confirming this match will complete the Financial Commitment, record the actual amount, consume the money spent, release only unused reserved money, recalculate both forecasts and preserve the history.</Text>
                  <View style={styles.actions}>
                    <Pressable style={styles.primary} disabled={busy} onPress={() => confirm(it.event.id, it.single_strong_match.commitment.id)} testID={`recon-confirm-${it.event.id}`}><Text style={styles.primaryText}>Confirm Match</Text></Pressable>
                    <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-reject-${it.event.id}`}><Text style={styles.secondaryText}>Reject Match</Text></Pressable>
                  </View>
                </>
              ) : it.matches.length > 0 ? (
                <>
                  <Text style={styles.body}>Multiple possible matches. Select one, or reject.</Text>
                  {it.matches.map((m: any) => (
                    <Pressable key={m.commitment.id} style={styles.matchRow} disabled={busy} onPress={() => confirm(it.event.id, m.commitment.id)} testID={`recon-pick-${it.event.id}-${m.commitment.id}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.mTitle}>{m.commitment.title}</Text>
                        <Text style={styles.mMeta}>{m.commitment.currency} {formatMoney(m.commitment.amount)} · due {dateLabel(m.commitment.due_date)} · {m.commitment.priority} · score {m.score}</Text>
                      </View>
                    </Pressable>
                  ))}
                  <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-none-${it.event.id}`}><Text style={styles.secondaryText}>None of these</Text></Pressable>
                </>
              ) : (
                <>
                  <Text style={styles.body}>No suitable match. Treat as unplanned?</Text>
                  <Pressable style={styles.secondary} disabled={busy} onPress={() => reject(it.event.id)} testID={`recon-unplanned-${it.event.id}`}><Text style={styles.secondaryText}>Yes, unplanned</Text></Pressable>
                </>
              )}
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
  meta: { fontSize: 11, color: colors.onSurfaceSecondary },
  body: { fontSize: 13, color: colors.onSurface, marginTop: spacing.xs, lineHeight: 18 },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, alignItems: "center", flex: 1 },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 13, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", flex: 1, marginTop: spacing.sm },
  secondaryText: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  matchRow: { padding: spacing.md, backgroundColor: colors.surface, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  mTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  mMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
});
