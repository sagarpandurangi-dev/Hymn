import { useEffect, useState } from "react";
import { Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { CURRENCY_LABEL } from "@/src/lib/portfolio/constants";
import { dateLabel, formatMoney, stateLabel } from "@/src/lib/finance/format";

const PRIORITIES = ["low", "medium", "high", "critical"];

/**
 * Wizard: collect fields → server-side decision assessment (§23) → user
 * chooses Edit / Rebalance / Proceed → reservation (§7) or override log (§24).
 */
export default function NewCommitment() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<string>("USD");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [dueDate, setDueDate] = useState<string>("");
  const [priority, setPriority] = useState<string>("");
  const [createTask, setCreateTask] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDue, setTaskDue] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessOpen, setAssessOpen] = useState(false);
  const [assessment, setAssessment] = useState<any | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [rebalanceOpen, setRebalanceOpen] = useState(false);
  const [rebalanceRows, setRebalanceRows] = useState<any[]>([]);
  const [rebalanceSel, setRebalanceSel] = useState<Record<string, "postpone" | "cancel" | undefined>>({});
  const [confirmOverrideOpen, setConfirmOverrideOpen] = useState(false);
  const [overrideComment, setOverrideComment] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const st = await api.getPortfolioSetupStatus();
        if (st?.reporting_currency) setCurrency(st.reporting_currency);
      } catch { /* ignore */ }
    })();
  }, []);

  const validate = (): string | null => {
    if (!title.trim()) return "Title is required.";
    const num = Number(amount);
    if (!amount || Number.isNaN(num) || num < 0) return "Amount must be a non-negative number.";
    if (!/^[A-Z]{3}$/.test(currency)) return "Currency must be a valid ISO code.";
    if (!dueDate) return "Due date is required.";
    if (!priority) return "Please select a priority.";
    if (createTask && !taskTitle.trim()) return "Task title is required when Create Task is on.";
    return null;
  };

  const startAssessment = async () => {
    setError(null);
    const err = validate();
    if (err) { setError(err); return; }
    setSaving(true);
    try {
      // 1) Create commitment as draft
      const created = await api.createFinancialCommitment({
        title: title.trim(), description: description.trim(),
        amount, currency, due_date: dueDate, priority,
        create_task: createTask, task_title: createTask ? taskTitle.trim() : undefined,
        task_due_date: createTask ? (taskDue || undefined) : undefined,
      });
      setCreatedId(created.id);
      // 2) Run backend decision assessment
      const ass = await api.runDecisionAssessment({ amount, currency, due_date: dueDate, priority });
      setAssessment(ass);
      setAssessOpen(true);
    } catch (e: any) {
      setError(e?.message || "Could not create commitment");
    } finally { setSaving(false); }
  };

  const proceedReserve = async () => {
    if (!createdId) return;
    setSaving(true);
    try {
      await api.reserveFinancialCommitment(createdId);
      setAssessOpen(false);
      router.replace(`/finance/commitments/${createdId}`);
    } catch (e: any) { Alert.alert("Could not reserve", e?.message || ""); } finally { setSaving(false); }
  };

  const proceedWithOverride = async () => {
    if (!createdId || !assessment) return;
    setSaving(true);
    try {
      await api.recordOverride({
        commitment_id: createdId,
        forecast_snapshot: assessment,
        liquidity_result: { projected_liquidity_by_due_date: assessment.projected_liquidity_by_due_date, shortfall: assessment.projected_shortfall, negative_months: assessment.negative_months },
        net_worth_result: { net_worth_impact: assessment.net_worth_impact },
        confidence: assessment.forecast_confidence,
        warning_classification: assessment.classification,
        projected_shortfall: assessment.projected_shortfall || undefined,
        affected_commitments: assessment.affected_commitments || [],
        user_comment: overrideComment.trim() || undefined,
      });
      await api.reserveFinancialCommitment(createdId);
      setConfirmOverrideOpen(false);
      setAssessOpen(false);
      router.replace(`/finance/commitments/${createdId}`);
    } catch (e: any) { Alert.alert("Could not proceed", e?.message || ""); } finally { setSaving(false); }
  };

  const openRebalance = async () => {
    setSaving(true);
    try {
      const rows = await api.rebalanceCandidates(currency, createdId || undefined);
      setRebalanceRows(rows);
      setRebalanceSel({});
      setRebalanceOpen(true);
    } catch (e: any) { Alert.alert("Could not load candidates", e?.message || ""); } finally { setSaving(false); }
  };

  const applyRebalance = async () => {
    // Apply user-selected actions manually per §25 — never auto.
    setSaving(true);
    try {
      for (const row of rebalanceRows) {
        const action = rebalanceSel[row.id];
        if (action === "cancel") {
          await api.cancelFinancialCommitment(row.id);
        } else if (action === "postpone") {
          // Postpone by 30 days as a safe default the user can further adjust in commitment detail.
          const d = new Date();
          d.setDate(d.getDate() + 30);
          const iso = d.toISOString().slice(0, 10);
          await api.postponeFinancialCommitment(row.id, iso);
        }
      }
      // Re-run the assessment with the new state.
      const ass = await api.runDecisionAssessment({ amount, currency, due_date: dueDate, priority });
      setAssessment(ass);
      setRebalanceOpen(false);
    } catch (e: any) { Alert.alert("Rebalance failed", e?.message || ""); } finally { setSaving(false); }
  };

  const editDraft = () => {
    setAssessOpen(false);
    if (createdId) router.replace(`/finance/commitments/${createdId}`);
  };

  const badgeStyle = (c: string) => c === "safe" ? { backgroundColor: colors.success } : c === "warning" ? { backgroundColor: "#e57c00" } : { backgroundColor: colors.error };
  const badgeLabel = (c: string) => c === "safe" ? "Safe" : c === "warning" ? "Warning" : "Severe risk";

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="New Financial Commitment" subtitle="Reserved money for a future decision" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Title</Text>
          <TextInput value={title} onChangeText={setTitle} placeholder="e.g. Laptop upgrade" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="fc-title" />
          <Text style={styles.label}>Description (optional)</Text>
          <TextInput value={description} onChangeText={setDescription} multiline style={[styles.input, { minHeight: 60 }]} testID="fc-desc" />
          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Amount</Text>
              <TextInput value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="fc-amount" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Currency</Text>
              <Pressable style={styles.input} onPress={() => setPickerOpen(true)} testID="fc-currency"><Text style={{ color: colors.onSurface }}>{CURRENCY_LABEL(currency)}</Text></Pressable>
            </View>
          </View>
          <Text style={styles.label}>Due date</Text>
          <DateTimeField mode="date" value={dueDate} onChange={setDueDate} testID="fc-due" />
          <Text style={styles.label}>Priority</Text>
          <View style={styles.chipRow}>
            {PRIORITIES.map((p) => (
              <Pressable key={p} style={[styles.chip, priority === p && styles.chipSel]} onPress={() => setPriority(p)} testID={`fc-priority-${p}`}>
                <Text style={[styles.chipText, priority === p && styles.chipTextSel]}>{p}</Text>
              </Pressable>
            ))}
          </View>
          <View style={styles.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Create linked task</Text>
              <Text style={styles.help}>Tracks the work; the reservation stays independent.</Text>
            </View>
            <Switch value={createTask} onValueChange={setCreateTask} testID="fc-create-task" />
          </View>
          {createTask && (
            <>
              <Text style={styles.label}>Task title</Text>
              <TextInput value={taskTitle} onChangeText={setTaskTitle} style={styles.input} testID="fc-task-title" />
              <Text style={styles.label}>Task due (optional)</Text>
              <DateTimeField mode="date" value={taskDue} onChange={setTaskDue} testID="fc-task-due" />
            </>
          )}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable onPress={startAssessment} disabled={saving} style={[styles.cta, saving && { opacity: 0.5 }]} testID="fc-continue">
            <Text style={styles.ctaText}>{saving ? "Preparing…" : "Assess & reserve"}</Text>
          </Pressable>
          <Text style={styles.note}>Nothing is reserved until you confirm on the assessment sheet.</Text>
        </ScrollView>
      </KeyboardAvoidingView>

      <CurrencyPickerModal visible={pickerOpen} selected={currency} onSelect={setCurrency} onClose={() => setPickerOpen(false)} />

      {/* Decision assessment sheet (§23) */}
      <Modal visible={assessOpen} animationType="slide" transparent onRequestClose={editDraft}>
        <View style={styles.sheetWrap}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Decision assessment</Text>
              <Pressable onPress={editDraft} hitSlop={12}><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
            </View>
            {assessment && (
              <View style={{ gap: spacing.xs }}>
                <View style={[styles.badge, badgeStyle(assessment.classification)]}>
                  <Text style={styles.badgeText}>{badgeLabel(assessment.classification)}</Text>
                </View>
                <Row label="Projected liquid on due date" val={`${currency} ${formatMoney(assessment.projected_liquidity_by_due_date || "0")}`} />
                {assessment.projected_shortfall ? <Row label="Projected shortfall" val={`${currency} ${formatMoney(assessment.projected_shortfall)}`} strong /> : null}
                <Row label="Net worth impact" val={`${currency} ${formatMoney(assessment.net_worth_impact || "0")}`} />
                <Row label="Forecast confidence" val={assessment.forecast_confidence} />
                {(assessment.assumptions_used || []).length > 0 && (
                  <Text style={styles.foot}>Assumptions: {assessment.assumptions_used.join(", ")}</Text>
                )}
                {assessment.negative_months?.length > 0 && (
                  <Text style={styles.warnLine}>Negative months: {assessment.negative_months.map((m: any) => m.month).join(", ")}</Text>
                )}
                {assessment.displaced_higher_priority?.length > 0 && (
                  <Text style={styles.warnLine}>Displaces higher-priority: {assessment.displaced_higher_priority.map((c: any) => c.title).join(", ")}</Text>
                )}
                {(assessment.affected_commitments || []).length > 0 && (
                  <>
                    <Text style={styles.subTitle}>Affected commitments (order: lowest priority → flexible → later due date)</Text>
                    {assessment.affected_commitments.slice(0, 6).map((c: any) => (
                      <Text key={c.id} style={styles.itemLine}>• {c.title} · {c.currency} {formatMoney(c.amount)} · due {dateLabel(c.due_date)} · {c.priority} · {stateLabel(c.state)}</Text>
                    ))}
                  </>
                )}
              </View>
            )}
            <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap", marginTop: spacing.md }}>
              <Pressable style={styles.secondary} onPress={editDraft} testID="fc-edit"><Text style={styles.secondaryText}>Edit</Text></Pressable>
              <Pressable style={styles.secondary} onPress={openRebalance} testID="fc-rebalance"><Text style={styles.secondaryText}>Rebalance</Text></Pressable>
              {assessment?.classification === "safe" ? (
                <Pressable style={styles.primary} onPress={proceedReserve} testID="fc-confirm"><Text style={styles.primaryText}>Confirm & reserve</Text></Pressable>
              ) : (
                <Pressable style={styles.warnBtn} onPress={() => setConfirmOverrideOpen(true)} testID="fc-proceed-anyway"><Text style={styles.warnBtnText}>Proceed Anyway</Text></Pressable>
              )}
            </View>
          </View>
        </View>
      </Modal>

      {/* Rebalance sheet (§25) */}
      <Modal visible={rebalanceOpen} animationType="slide" transparent onRequestClose={() => setRebalanceOpen(false)}>
        <View style={styles.sheetWrap}>
          <View style={[styles.sheetCard, { maxHeight: "80%" }]}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Rebalance</Text>
              <Pressable onPress={() => setRebalanceOpen(false)} hitSlop={12}><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>Select commitments to postpone or cancel. Nothing is applied until you confirm below. Linked tasks stay active; cancel them separately if desired.</Text>
            <ScrollView style={{ maxHeight: 380 }} contentContainerStyle={{ gap: spacing.sm }}>
              {rebalanceRows.map((r) => (
                <View key={r.id} style={styles.rebRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rebTitle}>{r.title}</Text>
                    <Text style={styles.rebMeta}>{r.currency} {formatMoney(r.amount)} · due {dateLabel(r.due_date)} · {r.priority} · {r.fixed_or_flexible || "—"}</Text>
                  </View>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <Pressable style={[styles.chipSmall, rebalanceSel[r.id] === "postpone" && styles.chipSel]} onPress={() => setRebalanceSel((s) => ({ ...s, [r.id]: s[r.id] === "postpone" ? undefined : "postpone" }))}><Text style={styles.chipText}>Postpone</Text></Pressable>
                    <Pressable style={[styles.chipSmall, rebalanceSel[r.id] === "cancel" && { backgroundColor: colors.error }]} onPress={() => setRebalanceSel((s) => ({ ...s, [r.id]: s[r.id] === "cancel" ? undefined : "cancel" }))}><Text style={styles.chipText}>Cancel</Text></Pressable>
                  </View>
                </View>
              ))}
            </ScrollView>
            <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={applyRebalance} testID="fc-apply-rebalance"><Text style={styles.primaryText}>Apply selected & re-assess</Text></Pressable>
          </View>
        </View>
      </Modal>

      {/* Override confirmation (§24) */}
      <Modal visible={confirmOverrideOpen} animationType="slide" transparent onRequestClose={() => setConfirmOverrideOpen(false)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Proceed with warning</Text>
              <Pressable onPress={() => setConfirmOverrideOpen(false)} hitSlop={12}><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>You are proceeding despite a {assessment?.classification === "warning" ? "warning" : "severe risk"} in the forecast. The exact assessment, forecast snapshot and confidence will be logged. Your choice remains final.</Text>
            <Text style={styles.label}>Optional comment</Text>
            <TextInput value={overrideComment} onChangeText={setOverrideComment} multiline style={[styles.input, { minHeight: 60 }]} placeholder="Why are you proceeding?" placeholderTextColor={colors.onSurfaceTertiary} testID="fc-override-comment" />
            <Pressable style={[styles.warnBtn, saving && { opacity: 0.5 }]} disabled={saving} onPress={proceedWithOverride} testID="fc-override-confirm"><Text style={styles.warnBtnText}>Confirm and reserve</Text></Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ label, val, strong }: { label: string; val: string; strong?: boolean }) {
  return <View style={styles.factRow}><Text style={styles.factLabel}>{label}</Text><Text style={[styles.factValue, strong && { color: colors.error }]}>{val}</Text></View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.md, marginBottom: spacing.xs },
  help: { fontSize: 11, color: colors.onSurfaceSecondary },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  chipSmall: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  chipSel: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 12, color: colors.onBrandTertiary },
  chipTextSel: { color: colors.onBrandPrimary, fontWeight: "600" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.md },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", marginTop: spacing.lg },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "700" },
  note: { textAlign: "center", fontSize: 11, color: colors.onSurfaceTertiary, marginTop: spacing.sm, fontStyle: "italic" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.sm },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  sheetBody: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  factRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.xs },
  factLabel: { fontSize: 13, color: colors.onSurfaceSecondary },
  factValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  badge: { alignSelf: "flex-start", paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  badgeText: { color: "#fff", fontSize: 12, fontWeight: "700", letterSpacing: 0.5 },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, alignItems: "center", flex: 1 },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  warnBtn: { backgroundColor: colors.error, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, alignItems: "center", flex: 1 },
  warnBtnText: { color: "#fff", fontSize: 14, fontWeight: "700" },
  foot: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: spacing.xs, fontStyle: "italic" },
  warnLine: { fontSize: 12, color: colors.error, fontWeight: "600" },
  subTitle: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.sm },
  itemLine: { fontSize: 12, color: colors.onSurface },
  rebRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm },
  rebTitle: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  rebMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
});
