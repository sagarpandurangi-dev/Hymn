import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import AccountPickerModal from "@/src/components/AccountPickerModal";
import { FoldAmount, FoldCard, FoldHero, FoldPill, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

type Action = "complete" | "cancel" | "postpone" | "keep-active" | "allocate" | null;

// Correction 2: build a device-local, timezone-aware ISO 8601 timestamp
// so the backend can normalise it to UTC without ever silently
// interpreting a naive wall-clock string as UTC.
function nowLocalIso(): string {
  const now = new Date();
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  const off = -now.getTimezoneOffset(); // minutes east of UTC
  const sign = off >= 0 ? "+" : "-";
  const oh = pad(Math.floor(Math.abs(off) / 60));
  const om = pad(Math.abs(off) % 60);
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}` +
    `${sign}${oh}:${om}`
  );
}

const STATE_TONE: Record<string, "neutral" | "info" | "ok" | "err" | "warn"> = {
  draft: "neutral", reserved: "info", partial: "warn", completed: "ok", cancelled: "neutral", expired: "err",
};
const STATE_LABEL: Record<string, string> = {
  draft: "Draft", reserved: "Reserved", partial: "Partial", completed: "Completed", cancelled: "Cancelled", expired: "Expired",
};

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
  // Correction 2: completion also needs a paying asset account +
  // explicit occurred_at. State kept alongside the action modal.
  const [accountId, setAccountId] = useState<string | null>(null);
  const [accountLabel, setAccountLabel] = useState<string>("Choose account");
  const [accountPickerOpen, setAccountPickerOpen] = useState(false);
  // Correction 3 — partial payment via allocations on an existing
  // APPLIED event. The picker below lists confirmed outflow events
  // of the same currency that still have unallocated amount left.
  const [eligibleEvents, setEligibleEvents] = useState<any[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [allocateAmount, setAllocateAmount] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const doc = await api.getFinancialCommitment(id);
      setC(doc);
      const trail = await api.getFinancialAudit("financial_commitment", id).catch(() => ({ entries: [] }));
      setAudit(trail?.entries || []);
      // Correction 3 — load candidate events for the "record partial
      // payment" flow. We only surface confirmed events whose
      // lifecycle is applied and whose currency matches the
      // commitment. The backend refuses any allocation that would
      // over-allocate the parent event.
      try {
        const evs = await api.listFinancialEvents({ currency: doc.currency, confirmation_status: "confirmed", limit: 200 });
        const cur = doc.currency;
        const eligible = (evs || []).filter((e: any) => {
          if (e.direction !== "outflow") return false;
          if (e.currency !== cur) return false;
          if (!["awaiting_reconciliation", "matched", "resolved_unplanned"].includes(e.lifecycle_status)) return false;
          const unalloc = parseFloat(e.unallocated_amount || "0");
          return isFinite(unalloc) && unalloc > 0;
        });
        setEligibleEvents(eligible);
      } catch { /* non-fatal */ }
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
        if (!accountId) { Alert.alert("Account required", "Pick the asset account this money came out of."); setBusy(false); return; }
        // Correction 2: send actual_amount + account_id + explicit
        // timezone-aware occurred_at. The backend refuses missing/
        // naive occurred_at when auto-creating the completion event.
        await api.completeFinancialCommitment(c.id, {
          actual_amount: actualAmount,
          account_id: accountId,
          occurred_at: nowLocalIso(),
        });
      } else if (a === "cancel") {
        await api.cancelFinancialCommitment(c.id);
      } else if (a === "postpone") {
        if (!newDue) { Alert.alert("New due date required", "Please pick a future date."); setBusy(false); return; }
        await api.postponeFinancialCommitment(c.id, newDue);
      } else if (a === "keep-active") {
        await api.keepActiveFinancialCommitment(c.id);
      } else if (a === "allocate") {
        if (!selectedEventId) { Alert.alert("Pick an event", "Choose an existing spending event to allocate from."); setBusy(false); return; }
        if (!allocateAmount) { Alert.alert("Amount required", "Enter how much of the event to apply to this commitment."); setBusy(false); return; }
        await api.createAllocation(selectedEventId, {
          target_type: "commitment",
          target_id: c.id,
          amount: allocateAmount,
        });
      }
      setAction(null); setActualAmount(""); setNewDue(""); setAccountId(null); setAccountLabel("Choose account");
      setSelectedEventId(null); setAllocateAmount("");
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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Commitment" />
      <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} />
    </SafeAreaView>
  );

  const canComplete = c.state === "reserved" || c.state === "expired" || c.state === "partial";
  const canCancel = c.state === "draft" || c.state === "reserved" || c.state === "expired" || c.state === "partial";
  const canPostpone = c.state === "reserved" || c.state === "expired" || c.state === "partial";
  const canReserve = c.state === "draft";
  const canKeepActive = c.state === "expired";
  const canAllocate = ["reserved", "expired", "partial"].includes(c.state) && eligibleEvents.length > 0;

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Commitment" subtitle={c.title} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.pillRow}>
          <FoldPill label={STATE_LABEL[c.state] || c.state} tone={STATE_TONE[c.state] || "neutral"} />
          {c.is_overdue ? <FoldPill label="Overdue" tone="err" /> : null}
        </View>

        <Text style={styles.title}>{c.title}</Text>
        {c.description ? <Text style={styles.desc}>{c.description}</Text> : null}

        <FoldHero currency={c.currency} amount={formatMoney(c.amount)} size="xl" caption={`Due ${dateLabel(c.due_date)} · ${c.priority} priority`} />
        {c.original_due_date && c.original_due_date !== c.due_date ? (
          <Text style={styles.meta}>Original due {dateLabel(c.original_due_date)} · postponed {c.postpone_count}×</Text>
        ) : null}

        {/* Correction 3 — payment progress derived from active
            allocations on APPLIED events. Always shown once any
            payment has landed (even if state is still 'reserved'
            because the last allocation didn't cover the full amount). */}
        {parseFloat(c.paid_amount || "0") > 0 ? (
          <View>
            <FoldSectionHeader label="Payment progress" />
            <FoldCard>
              <FoldRow first label="Paid" right={<FoldAmount currency={c.currency} value={formatMoney(c.paid_amount)} tone="positive" />} />
              <FoldRow label="Remaining" right={<FoldAmount currency={c.currency} value={formatMoney(c.remaining_amount)} tone={parseFloat(c.remaining_amount || "0") > 0 ? "muted" : "positive"} />} />
            </FoldCard>
          </View>
        ) : null}

        {c.task_id ? (
          <FoldCard>
            <Pressable style={styles.linkRow} onPress={() => router.push(`/tasks/${c.task_id}`)}>
              <Ionicons name="link-outline" size={14} color={financeColors.accent} />
              <Text style={styles.linkText}>View linked task</Text>
              <Ionicons name="chevron-forward" size={14} color={financeColors.inkFaint} style={{ marginLeft: "auto" }} />
            </Pressable>
          </FoldCard>
        ) : null}

        {c.state === "completed" ? (
          <View>
            <FoldSectionHeader label="Completion" />
            <FoldCard>
              <FoldRow first label="Actual amount" right={<FoldAmount currency={c.currency} value={formatMoney(c.actual_amount)} />} />
              <FoldRow label="Variance" right={<FoldAmount currency={c.currency} value={formatMoney(c.variance)} />} />
              <FoldRow label="Unused reservation returned" right={<FoldAmount currency={c.currency} value={formatMoney(c.unused_reservation)} tone="positive" />} />
              <FoldRow label="Overrun" right={<FoldAmount currency={c.currency} value={formatMoney(c.overrun_amount)} tone={c.overrun_amount && Number(c.overrun_amount) > 0 ? "negative" : "muted"} />} />
              <FoldRow label="Completed at" right={<Text style={financeType.amount as any}>{c.completed_at?.slice(0, 10) || ""}</Text>} />
            </FoldCard>
          </View>
        ) : null}

        <View style={styles.actionsRow}>
          {canReserve ? <Pressable style={styles.primary} disabled={busy} onPress={reserve} testID="fc-reserve"><Text style={styles.primaryText}>Reserve now</Text></Pressable> : null}
          {canComplete ? <Pressable style={styles.primary} disabled={busy} onPress={() => setAction("complete")} testID="fc-complete-open"><Text style={styles.primaryText}>Complete</Text></Pressable> : null}
          {canAllocate ? <Pressable style={styles.secondary} disabled={busy} onPress={() => setAction("allocate")} testID="fc-allocate-open"><Text style={styles.secondaryText}>Record partial payment</Text></Pressable> : null}
          {canPostpone ? <Pressable style={styles.secondary} disabled={busy} onPress={() => setAction("postpone")} testID="fc-postpone-open"><Text style={styles.secondaryText}>Postpone</Text></Pressable> : null}
          {canKeepActive ? <Pressable style={styles.secondary} disabled={busy} onPress={() => run("keep-active")} testID="fc-keep-active"><Text style={styles.secondaryText}>Keep active</Text></Pressable> : null}
          {canCancel ? <Pressable style={styles.danger} disabled={busy} onPress={() => setAction("cancel")} testID="fc-cancel-open"><Text style={styles.dangerText}>Cancel</Text></Pressable> : null}
        </View>

        <View>
          <FoldSectionHeader
            label="Audit trail"
            action={{ label: "Full history", onPress: () => router.push(`/finance/audit/financial_commitment/${c.id}`) }}
          />
          {audit.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No history yet.</Text></FoldCard>
          ) : (
            <FoldCard>
              {audit.slice(0, 6).map((e, idx) => (
                <FoldRow
                  key={e.id}
                  first={idx === 0}
                  label={e.action}
                  meta={`${e.timestamp?.slice(0, 16).replace("T", " ")} · ${e.source}`}
                />
              ))}
            </FoldCard>
          )}
        </View>
      </ScrollView>

      <Modal visible={!!action} animationType="slide" transparent onRequestClose={() => setAction(null)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>{action === "complete" ? "Complete" : action === "cancel" ? "Cancel" : action === "postpone" ? "Postpone" : action === "allocate" ? "Record partial payment" : ""}</Text>
              <Pressable onPress={() => setAction(null)} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            {action === "complete" ? (
              <>
                <Text style={styles.sheetBody}>Completing records the actual spend, consumes the amount spent, releases any unused reserved money to the available pool, recalculates forecasts and preserves full history.</Text>
                <Text style={styles.label}>ACTUAL AMOUNT ({c.currency})</Text>
                <TextInput value={actualAmount} onChangeText={setActualAmount} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={financeColors.inkFaint} style={styles.input} testID="fc-actual-amount" />
                <Text style={styles.label}>PAYING ACCOUNT</Text>
                <Pressable onPress={() => setAccountPickerOpen(true)} style={styles.input} testID="fc-account-select">
                  <Text style={{ color: accountId ? financeColors.ink : financeColors.inkFaint, fontSize: 15 }}>{accountLabel}</Text>
                </Pressable>
                {!accountId ? (
                  <Text style={{ fontSize: 12, color: financeColors.inkFaint, marginTop: 4 }}>
                    Pick the {c.currency} asset account this money came out of. Completion is disabled until an eligible account is chosen.
                  </Text>
                ) : null}
                <Pressable style={[styles.primary, (busy || !accountId || !actualAmount) && { opacity: 0.5 }]} disabled={busy || !accountId || !actualAmount} onPress={() => run("complete")} testID="fc-complete-submit">
                  <Text style={styles.primaryText}>Confirm completion</Text>
                </Pressable>
              </>
            ) : null}
            {action === "cancel" ? (
              <>
                <Text style={styles.sheetBody}>Cancelling releases the full reservation and returns it to the available pool. Future forecast impact will be removed. History remains. The linked task, if any, stays active — cancel it separately if needed.</Text>
                <Pressable style={[styles.danger, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => run("cancel")} testID="fc-cancel-submit">
                  <Text style={styles.dangerText}>Confirm cancel</Text>
                </Pressable>
              </>
            ) : null}
            {action === "postpone" ? (
              <>
                <Text style={styles.sheetBody}>Postponing keeps the reservation and moves the due date. Affected forecast months will be recalculated. The original due date remains in the audit trail.</Text>
                <Text style={styles.label}>NEW DUE DATE</Text>
                <DateTimeField mode="date" value={newDue} onChange={setNewDue} testID="fc-postpone-date" />
                <Pressable style={[styles.primary, busy && { opacity: 0.5 }]} disabled={busy} onPress={() => run("postpone")} testID="fc-postpone-submit">
                  <Text style={styles.primaryText}>Confirm postpone</Text>
                </Pressable>
              </>
            ) : null}
            {action === "allocate" ? (
              <>
                <Text style={styles.sheetBody}>Pick an existing spending event and how much of it to apply to this commitment. The event stays as-is — allocations only classify the money, they never move an account balance.</Text>
                <Text style={styles.label}>EVENT</Text>
                {eligibleEvents.length === 0 ? (
                  <Text style={{ fontSize: 12, color: financeColors.inkFaint, marginTop: 4 }}>No confirmed {c.currency} outflow events with unallocated amount right now.</Text>
                ) : (
                  <ScrollView style={{ maxHeight: 220 }}>
                    {eligibleEvents.map((e) => (
                      <Pressable
                        key={e.id}
                        onPress={() => setSelectedEventId(e.id)}
                        style={[styles.eventRow, selectedEventId === e.id && styles.eventRowSel]}
                        testID={`fc-allocate-event-${e.id}`}
                      >
                        <Text style={styles.eventPrimary} numberOfLines={1}>{e.description || "Untitled event"}</Text>
                        <Text style={styles.eventMeta}>{dateLabel(e.event_date)} · {c.currency} {formatMoney(e.amount)} · unallocated {formatMoney(e.unallocated_amount || "0")}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                )}
                <Text style={styles.label}>AMOUNT ({c.currency})</Text>
                <TextInput value={allocateAmount} onChangeText={setAllocateAmount} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={financeColors.inkFaint} style={styles.input} testID="fc-allocate-amount" />
                <Pressable style={[styles.primary, (busy || !selectedEventId || !allocateAmount) && { opacity: 0.5 }]} disabled={busy || !selectedEventId || !allocateAmount} onPress={() => run("allocate")} testID="fc-allocate-submit">
                  <Text style={styles.primaryText}>Apply to this commitment</Text>
                </Pressable>
              </>
            ) : null}
          </View>
        </KeyboardAvoidingView>
      </Modal>
      <AccountPickerModal
        visible={accountPickerOpen}
        currency={c.currency}
        selectedId={accountId}
        onSelect={async (id) => {
          setAccountId(id);
          if (!id) { setAccountLabel("Assign later"); return; }
          try {
            const rows = await api.listFinancialAccounts();
            const match = rows.find((r) => r.id === id);
            setAccountLabel(match ? `${match.name} (${match.currency})` : "Account selected");
          } catch {
            setAccountLabel("Account selected");
          }
        }}
        onClose={() => setAccountPickerOpen(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  pillRow: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  title: { ...financeType.screenTitle, fontSize: 22 } as any,
  desc: { fontSize: 13, color: financeColors.inkMuted, lineHeight: 19 },
  meta: { fontSize: 11.5, color: financeColors.inkMuted, letterSpacing: 0.3 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: financeSpace.lg, paddingVertical: 14, backgroundColor: "#FFFFFF" },
  linkText: { ...financeType.body, color: financeColors.accent, fontWeight: "600" } as any,
  actionsRow: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm, marginTop: financeSpace.xs },
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill },
  primaryText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  secondaryText: { color: financeColors.ink, fontSize: 13, fontWeight: "600" },
  danger: { paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.danger },
  dangerText: { color: financeColors.danger, fontSize: 13, fontWeight: "700" },
  empty: { fontSize: 12.5, color: financeColors.inkMuted, padding: financeSpace.lg, textAlign: "center", fontStyle: "italic" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: financeColors.page, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.xl, paddingBottom: financeSpace.xxxl, gap: financeSpace.md },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { ...financeType.screenTitle, fontSize: 18 } as any,
  sheetBody: { ...financeType.body, color: financeColors.inkMuted } as any,
  label: { ...financeType.sectionLabel } as any,
  input: { backgroundColor: "#FFFFFF", borderRadius: financeRadius.sm, paddingHorizontal: financeSpace.lg, paddingVertical: financeSpace.md, fontSize: 15, color: financeColors.ink, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  eventRow: { paddingHorizontal: financeSpace.md, paddingVertical: financeSpace.sm, borderRadius: financeRadius.sm, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, backgroundColor: "#FFFFFF", marginBottom: financeSpace.xs },
  eventRowSel: { borderColor: financeColors.ink, backgroundColor: financeColors.pillBg },
  eventPrimary: { fontSize: 13, color: financeColors.ink, fontWeight: "600" },
  eventMeta: { fontSize: 11, color: financeColors.inkMuted, marginTop: 2 },
});
