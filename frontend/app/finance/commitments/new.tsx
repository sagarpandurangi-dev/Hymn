import { useEffect, useState } from "react";
import { Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { CURRENCY_LABEL } from "@/src/lib/portfolio/constants";
import { FoldAmount, FoldCard, FoldPill, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney, stateLabel } from "@/src/lib/finance/format";

const PRIORITIES = ["low", "medium", "high", "critical"];

const CLASSIFICATION_TONE: Record<string, "ok" | "warn" | "err"> = {
  safe: "ok",
  warning: "warn",
  severe: "err",
};

/**
 * Wizard: fields → server-side decision assessment (§23) →
 * Edit / Rebalance / Proceed → reservation (§7) or override log (§24).
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
      const created = await api.createFinancialCommitment({
        title: title.trim(), description: description.trim(),
        amount, currency, due_date: dueDate, priority,
        create_task: createTask, task_title: createTask ? taskTitle.trim() : undefined,
        task_due_date: createTask ? (taskDue || undefined) : undefined,
      });
      setCreatedId(created.id);
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
    setSaving(true);
    try {
      for (const row of rebalanceRows) {
        const action = rebalanceSel[row.id];
        if (action === "cancel") {
          await api.cancelFinancialCommitment(row.id);
        } else if (action === "postpone") {
          const d = new Date();
          d.setDate(d.getDate() + 30);
          const iso = d.toISOString().slice(0, 10);
          await api.postponeFinancialCommitment(row.id, iso);
        }
      }
      const ass = await api.runDecisionAssessment({ amount, currency, due_date: dueDate, priority });
      setAssessment(ass);
      setRebalanceOpen(false);
    } catch (e: any) { Alert.alert("Rebalance failed", e?.message || ""); } finally { setSaving(false); }
  };

  const editDraft = () => {
    setAssessOpen(false);
    if (createdId) router.replace(`/finance/commitments/${createdId}`);
  };

  const classificationLabel = (c: string) => c === "safe" ? "Safe" : c === "warning" ? "Warning" : "Severe risk";

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="New commitment" subtitle="Reserved money for a future decision" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <FoldCard style={styles.formCard}>
            <Text style={styles.label}>TITLE</Text>
            <TextInput value={title} onChangeText={setTitle} placeholder="e.g. Laptop upgrade" placeholderTextColor={financeColors.inkFaint} style={styles.input} testID="fc-title" />
            <Text style={styles.label}>DESCRIPTION (OPTIONAL)</Text>
            <TextInput value={description} onChangeText={setDescription} multiline style={[styles.input, { minHeight: 60 }]} testID="fc-desc" />
            <View style={{ flexDirection: "row", gap: financeSpace.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>AMOUNT</Text>
                <TextInput value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={financeColors.inkFaint} style={styles.input} testID="fc-amount" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>CURRENCY</Text>
                <Pressable style={styles.input} onPress={() => setPickerOpen(true)} testID="fc-currency">
                  <Text style={{ color: financeColors.ink }}>{CURRENCY_LABEL(currency)}</Text>
                </Pressable>
              </View>
            </View>
            <Text style={styles.label}>DUE DATE</Text>
            <DateTimeField mode="date" value={dueDate} onChange={setDueDate} testID="fc-due" />
            <Text style={styles.label}>PRIORITY</Text>
            <View style={styles.chipRow}>
              {PRIORITIES.map((p) => (
                <Pressable key={p} style={[styles.chip, priority === p && styles.chipSel]} onPress={() => setPriority(p)} testID={`fc-priority-${p}`}>
                  <Text style={[styles.chipText, priority === p && styles.chipTextSel]}>{p}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.switchRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>CREATE LINKED TASK</Text>
                <Text style={styles.help}>Tracks the work; the reservation stays independent.</Text>
              </View>
              <Switch value={createTask} onValueChange={setCreateTask} testID="fc-create-task" />
            </View>
            {createTask ? (
              <>
                <Text style={styles.label}>TASK TITLE</Text>
                <TextInput value={taskTitle} onChangeText={setTaskTitle} style={styles.input} testID="fc-task-title" />
                <Text style={styles.label}>TASK DUE (OPTIONAL)</Text>
                <DateTimeField mode="date" value={taskDue} onChange={setTaskDue} testID="fc-task-due" />
              </>
            ) : null}
          </FoldCard>

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
              <Pressable onPress={editDraft} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            {assessment ? (
              <View style={{ gap: financeSpace.xs }}>
                <FoldPill label={classificationLabel(assessment.classification)} tone={CLASSIFICATION_TONE[assessment.classification] || "neutral"} />
                <FoldCard style={{ marginTop: financeSpace.sm }}>
                  <FoldRow first label="Projected liquid on due date" right={<FoldAmount currency={currency} value={formatMoney(assessment.projected_liquidity_by_due_date || "0")} />} />
                  {assessment.projected_shortfall ? (
                    <FoldRow label="Projected shortfall" right={<FoldAmount currency={currency} value={formatMoney(assessment.projected_shortfall)} tone="negative" />} strong />
                  ) : null}
                  <FoldRow label="Net worth impact" right={<FoldAmount currency={currency} value={formatMoney(assessment.net_worth_impact || "0")} />} />
                  <FoldRow label="Forecast confidence" right={<Text style={financeType.amount as any}>{assessment.forecast_confidence}</Text>} />
                </FoldCard>
                {(assessment.assumptions_used || []).length > 0 ? (
                  <Text style={styles.foot}>Assumptions · {assessment.assumptions_used.join(", ")}</Text>
                ) : null}
                {assessment.negative_months?.length > 0 ? (
                  <Text style={styles.warnLine}>Negative months · {assessment.negative_months.map((m: any) => m.month).join(", ")}</Text>
                ) : null}
                {assessment.displaced_higher_priority?.length > 0 ? (
                  <Text style={styles.warnLine}>Displaces higher-priority · {assessment.displaced_higher_priority.map((c: any) => c.title).join(", ")}</Text>
                ) : null}
                {(assessment.affected_commitments || []).length > 0 ? (
                  <>
                    <Text style={styles.subTitle}>AFFECTED COMMITMENTS</Text>
                    {assessment.affected_commitments.slice(0, 6).map((c: any) => (
                      <Text key={c.id} style={styles.itemLine}>• {c.title} · {c.currency} {formatMoney(c.amount)} · due {dateLabel(c.due_date)} · {c.priority} · {stateLabel(c.state)}</Text>
                    ))}
                  </>
                ) : null}
              </View>
            ) : null}
            <View style={{ flexDirection: "row", gap: financeSpace.sm, flexWrap: "wrap", marginTop: financeSpace.md }}>
              <Pressable style={styles.secondary} onPress={editDraft} testID="fc-edit"><Text style={styles.secondaryText}>Edit</Text></Pressable>
              <Pressable style={styles.secondary} onPress={openRebalance} testID="fc-rebalance"><Text style={styles.secondaryText}>Rebalance</Text></Pressable>
              {assessment?.classification === "safe" ? (
                <Pressable style={styles.primary} onPress={proceedReserve} testID="fc-confirm"><Text style={styles.primaryText}>Confirm & reserve</Text></Pressable>
              ) : (
                <Pressable style={styles.warnBtn} onPress={() => setConfirmOverrideOpen(true)} testID="fc-proceed-anyway"><Text style={styles.warnBtnText}>Proceed anyway</Text></Pressable>
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
              <Pressable onPress={() => setRebalanceOpen(false)} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>Select commitments to postpone or cancel. Nothing is applied until you confirm. Linked tasks stay active; cancel them separately if desired.</Text>
            <ScrollView style={{ maxHeight: 380 }} contentContainerStyle={{ gap: financeSpace.sm }}>
              {rebalanceRows.map((r) => (
                <FoldCard key={r.id} style={styles.rebCard}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rebTitle}>{r.title}</Text>
                    <Text style={styles.rebMeta}>{r.currency} {formatMoney(r.amount)} · due {dateLabel(r.due_date)} · {r.priority} · {r.fixed_or_flexible || "—"}</Text>
                  </View>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <Pressable style={[styles.chipSmall, rebalanceSel[r.id] === "postpone" && styles.chipSel]} onPress={() => setRebalanceSel((s) => ({ ...s, [r.id]: s[r.id] === "postpone" ? undefined : "postpone" }))}>
                      <Text style={[styles.chipText, rebalanceSel[r.id] === "postpone" && styles.chipTextSel]}>Postpone</Text>
                    </Pressable>
                    <Pressable style={[styles.chipSmall, rebalanceSel[r.id] === "cancel" && styles.chipDanger]} onPress={() => setRebalanceSel((s) => ({ ...s, [r.id]: s[r.id] === "cancel" ? undefined : "cancel" }))}>
                      <Text style={[styles.chipText, rebalanceSel[r.id] === "cancel" && { color: "#FFFFFF" }]}>Cancel</Text>
                    </Pressable>
                  </View>
                </FoldCard>
              ))}
            </ScrollView>
            <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={applyRebalance} testID="fc-apply-rebalance">
              <Text style={styles.primaryText}>Apply selected & re-assess</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Override confirmation (§24) */}
      <Modal visible={confirmOverrideOpen} animationType="slide" transparent onRequestClose={() => setConfirmOverrideOpen(false)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Proceed with warning</Text>
              <Pressable onPress={() => setConfirmOverrideOpen(false)} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>You are proceeding despite a {assessment?.classification === "warning" ? "warning" : "severe risk"} in the forecast. The exact assessment, forecast snapshot and confidence will be logged. Your choice remains final.</Text>
            <Text style={styles.label}>OPTIONAL COMMENT</Text>
            <TextInput value={overrideComment} onChangeText={setOverrideComment} multiline style={[styles.input, { minHeight: 60 }]} placeholder="Why are you proceeding?" placeholderTextColor={financeColors.inkFaint} testID="fc-override-comment" />
            <Pressable style={[styles.warnBtn, saving && { opacity: 0.5 }]} disabled={saving} onPress={proceedWithOverride} testID="fc-override-confirm">
              <Text style={styles.warnBtnText}>Confirm and reserve</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  formCard: { padding: financeSpace.lg, gap: 4 },
  label: { ...financeType.sectionLabel, marginTop: financeSpace.md, marginBottom: financeSpace.xs } as any,
  help: { fontSize: 11, color: financeColors.inkMuted },
  input: {
    backgroundColor: "#FBFBF6",
    borderRadius: financeRadius.sm,
    paddingHorizontal: financeSpace.md,
    paddingVertical: financeSpace.md,
    fontSize: 15,
    color: financeColors.ink,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: financeColors.cardBorder,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm, marginTop: 4 },
  chip: { paddingHorizontal: financeSpace.md, paddingVertical: financeSpace.sm, borderRadius: financeRadius.pill, backgroundColor: "#FBFBF6", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  chipSmall: { paddingHorizontal: financeSpace.md, paddingVertical: 6, borderRadius: financeRadius.pill, backgroundColor: "#FBFBF6", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  chipSel: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipDanger: { backgroundColor: financeColors.danger, borderColor: financeColors.danger },
  chipText: { fontSize: 12.5, color: financeColors.ink, fontWeight: "500" },
  chipTextSel: { color: "#FBFBF6", fontWeight: "700" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: financeSpace.md, marginTop: financeSpace.md },
  error: { color: financeColors.danger, fontSize: 13, marginTop: financeSpace.xs, paddingHorizontal: 2 },
  cta: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center", marginTop: financeSpace.md },
  ctaText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700", letterSpacing: 0.4 },
  note: { textAlign: "center", fontSize: 11, color: financeColors.inkFaint, marginTop: financeSpace.sm, fontStyle: "italic", letterSpacing: 0.3 },
  sheetWrap: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: financeColors.page, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.xl, paddingBottom: financeSpace.xxxl, gap: financeSpace.sm },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { ...financeType.screenTitle, fontSize: 18 } as any,
  sheetBody: { ...financeType.body, color: financeColors.inkMuted } as any,
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, alignItems: "center", flex: 1 },
  primaryText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center" },
  secondaryText: { color: financeColors.ink, fontSize: 13, fontWeight: "600" },
  warnBtn: { backgroundColor: financeColors.danger, paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, alignItems: "center", flex: 1 },
  warnBtnText: { color: "#FFFFFF", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  foot: { fontSize: 11, color: financeColors.inkFaint, marginTop: financeSpace.xs, fontStyle: "italic" },
  warnLine: { fontSize: 12, color: financeColors.danger, fontWeight: "600" },
  subTitle: { ...financeType.sectionLabel, marginTop: financeSpace.sm } as any,
  itemLine: { fontSize: 12, color: financeColors.ink, lineHeight: 18 },
  rebCard: { flexDirection: "row", alignItems: "center", gap: financeSpace.sm, padding: financeSpace.md },
  rebTitle: { fontSize: 13, fontWeight: "600", color: financeColors.ink },
  rebMeta: { fontSize: 11, color: financeColors.inkMuted, marginTop: 2 },
});
