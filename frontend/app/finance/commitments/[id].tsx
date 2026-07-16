import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { dateLabel, formatMoney, stateColor, stateLabel } from "@/src/lib/finance/format";

type Action = "complete" | "cancel" | "postpone" | "keep-active" | null;

export default function CommitmentDetail() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [c, setC] = useState<any | null>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<Action>(null);
  const [actualAmount, setActualAmount] = useState<string>("");
  const [newDue, setNewDue] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const doc = await api.getFinancialCommitment(id);
      setC(doc);
      const trail = await api.getFinancialAudit("financial_commitment", id).catch(() => ({ entries: [] }));
      setAudit(trail?.entries || []);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not load commitment");
    }
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const run = async (a: Action) => {
    if (!c) return;
    setBusy(true);
    try {
      if (a === "complete") {
        if (!actualAmount) { Alert.alert("Actual amount required", "Please enter the amount actually spent."); setBusy(false); return; }
        await api.completeFinancialCommitment(c.id, { actual_amount: actualAmount });
      } else if (a === "cancel") {
        await api.cancelFinancialCommitment(c.id);
      } else if (a === "postpone") {
        if (!newDue) { Alert.alert("New due date required", "Please pick a future date."); setBusy(false); return; }
        await api.postponeFinancialCommitment(c.id, newDue);
      } else if (a === "keep-active") {
        await api.keepActiveFinancialCommitment(c.id);
      }
      setAction(null);
      setActualAmount("");
      setNewDue("");
      await load();
    } catch (e: any) {
      Alert.alert("Action failed", e?.message || "");
    } finally { setBusy(false); }
  };

  const reserve = async () => {
    if (!c) return;
    setBusy(true);
    try { await api.reserveFinancialCommitment(c.id); await load(); } catch (e: any) { Alert.alert("Could not reserve", e?.message || ""); }
    setBusy(false);
  };

  if (loading || !c) return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}><FinanceHeader title="Financial Commitment" /><ActivityIndicator style={{ marginTop: spacing.xxxl }} /></SafeAreaView>
  );

  const canComplete = c.state === "reserved" || c.state === "expired";
  const canCancel = c.state === "draft" || c.state === "reserved" || c.state === "expired";
  const canPostpone = c.state === "reserved" || c.state === "expired";
  const canReserve = c.state === "draft";
  const canKeepActive = c.state === "expired";

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Financial Commitment" subtitle={c.title} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.headerCard}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={[styles.chip, { backgroundColor: stateColor(c.state) }]}><Text style={styles.chipText}>{stateLabel(c.state)}</Text></View>
            {c.is_overdue && <View style={[styles.chip, { backgroundColor: colors.error }]}><Text style={styles.chipText}>OVERDUE</Text></View>}
          </View>
          <Text style={styles.title}>{c.title}</Text>
          {c.description ? <Text style={styles.desc}>{c.description}</Text> : null}
          <Text style={styles.big}>{c.currency} {formatMoney(c.amount)}</Text>
          <Text style={styles.meta}>Due {dateLabel(c.due_date)} · priority {c.priority}</Text>
          {c.original_due_date !== c.due_date && <Text style={styles.meta}>Original due: {dateLabel(c.original_due_date)} · postponed {c.postpone_count}x</Text>}
          {c.task_id && (
            <Pressable style={styles.linkRow} onPress={() => router.push(`/tasks/${c.task_id}`)}>
              <Ionicons name="link-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.linkText}>View linked task</Text>
            </Pressable>
          )}
        </View>

        {c.state === "completed" && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Completion</Text>
            <Row label="Actual amount" val={`${c.currency} ${formatMoney(c.actual_amount)}`} />
            <Row label="Variance" val={`${c.currency} ${formatMoney(c.variance)}`} />
            <Row label="Unused reservation returned" val={`${c.currency} ${formatMoney(c.unused_reservation)}`} />
            <Row label="Overrun" val={`${c.currency} ${formatMoney(c.overrun_amount)}`} />
            <Row label="Completed at" val={c.completed_at?.slice(0, 10) || ""} />
          </View>
        )}

        <View style={styles.actionsRow}>
          {canReserve && <Pressable style={styles.primary} disabled={busy} onPress={reserve} testID="fc-reserve"><Text style={styles.primaryText}>Reserve now</Text></Pressable>}
          {canComplete && <Pressable style={styles.primary} disabled={busy} onPress={() => setAction("complete")} testID="fc-complete-open"><Text style={styles.primaryText}>Complete</Text></Pressable>}
          {canPostpone && <Pressable style={styles.secondary} disabled={busy} onPress={() => setAction("postpone")} testID="fc-postpone-open"><Text style={styles.secondaryText}>Postpone</Text></Pressable>}
          {canKeepActive && <Pressable style={styles.secondary} disabled={busy} onPress={() => run("keep-active")} testID="fc-keep-active"><Text style={styles.secondaryText}>Keep active</Text></Pressable>}
          {canCancel && <Pressable style={styles.danger} disabled={busy} onPress={() => setAction("cancel")} testID="fc-cancel-open"><Text style={styles.dangerText}>Cancel</Text></Pressable>}
        </View>

        <View style={styles.section}>
          <Pressable onPress={() => router.push(`/finance/audit/financial_commitment/${c.id}`)}>
            <Text style={styles.sectionTitle}>Audit trail · tap for full history</Text>
          </Pressable>
          {audit.slice(0, 6).map((e) => (
            <View key={e.id} style={styles.auditRow}>
              <Text style={styles.auditAction}>{e.action}</Text>
              <Text style={styles.auditMeta}>{e.timestamp?.slice(0, 16).replace("T", " ")} · {e.source}</Text>
            </View>
          ))}
          {audit.length === 0 && <Text style={styles.empty}>No history yet.</Text>}
        </View>
      </ScrollView>

      <Modal visible={!!action} animationType="slide" transparent onRequestClose={() => setAction(null)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>{action === "complete" ? "Complete" : action === "cancel" ? "Cancel" : action === "postpone" ? "Postpone" : ""}</Text>
              <Pressable onPress={() => setAction(null)} hitSlop={12}><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
            </View>
            {action === "complete" && (
              <>
                <Text style={styles.sheetBody}>Completing records the actual spend, consumes the amount spent, releases any unused reserved money to the available pool, recalculates your forecasts and preserves full history.</Text>
                <Text style={styles.label}>Actual amount ({c.currency})</Text>
                <TextInput value={actualAmount} onChangeText={setActualAmount} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="fc-actual-amount" />
                <Pressable style={[styles.primary, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => run("complete")} testID="fc-complete-submit"><Text style={styles.primaryText}>Confirm completion</Text></Pressable>
              </>
            )}
            {action === "cancel" && (
              <>
                <Text style={styles.sheetBody}>Cancelling releases the full reservation and returns it to the available pool. Future forecast impact will be removed. History remains. The linked task, if any, stays active — cancel it separately if needed.</Text>
                <Pressable style={[styles.danger, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => run("cancel")} testID="fc-cancel-submit"><Text style={styles.dangerText}>Confirm cancel</Text></Pressable>
              </>
            )}
            {action === "postpone" && (
              <>
                <Text style={styles.sheetBody}>Postponing keeps the reservation and moves the due date. Affected forecast months will be recalculated. The original due date remains in the audit trail.</Text>
                <Text style={styles.label}>New due date</Text>
                <DateTimeField mode="date" value={newDue} onChange={setNewDue} testID="fc-postpone-date" />
                <Pressable style={[styles.primary, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => run("postpone")} testID="fc-postpone-submit"><Text style={styles.primaryText}>Confirm postpone</Text></Pressable>
              </>
            )}
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ label, val }: { label: string; val: string }) {
  return <View style={styles.row}><Text style={styles.rowLabel}>{label}</Text><Text style={styles.rowValue}>{val}</Text></View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.xxxl },
  headerCard: { padding: spacing.lg, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, gap: spacing.xs },
  title: { fontSize: 20, color: colors.onSurface, fontWeight: "700" },
  desc: { fontSize: 13, color: colors.onSurfaceSecondary },
  big: { fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.md },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary },
  chip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill, alignSelf: "flex-start", marginRight: 4 },
  chipText: { fontSize: 10, color: "#fff", fontWeight: "700", letterSpacing: 0.5 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.sm },
  linkText: { color: colors.brandPrimary, fontSize: 13, fontWeight: "600" },
  section: { gap: spacing.xs, backgroundColor: colors.surfaceSecondary, padding: spacing.md, borderRadius: radius.md },
  sectionTitle: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginBottom: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.xs },
  rowLabel: { fontSize: 13, color: colors.onSurface },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  auditRow: { paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  auditAction: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  auditMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  empty: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic" },
  actionsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  danger: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.error, alignItems: "center" },
  dangerText: { color: colors.error, fontSize: 14, fontWeight: "700" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  sheetBody: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
});
