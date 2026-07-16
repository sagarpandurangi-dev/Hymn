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
import { formatMoney } from "@/src/lib/finance/format";

const PRIORITIES = ["low", "medium", "high", "critical"];

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
  const [reviewOpen, setReviewOpen] = useState(false);
  const [preview, setPreview] = useState<any | null>(null);

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
        amount: amount, currency, due_date: dueDate, priority,
        create_task: createTask, task_title: createTask ? taskTitle.trim() : undefined,
        task_due_date: createTask ? (taskDue || undefined) : undefined,
      });
      // Fetch the reserved snapshot so users see the lien impact BEFORE confirming.
      const [reservedRow, liquidity] = await Promise.all([
        api.getFinanceReserved().catch(() => null),
        api.getFinanceAvailableLiquidity().catch(() => null),
      ]);
      setPreview({ commitment: created, reserved: reservedRow, liquidity });
      setReviewOpen(true);
    } catch (e: any) {
      setError(e?.message || "Could not create commitment");
    } finally {
      setSaving(false);
    }
  };

  const confirmReservation = async () => {
    if (!preview?.commitment?.id) return;
    setSaving(true);
    try {
      await api.reserveFinancialCommitment(preview.commitment.id);
      setReviewOpen(false);
      router.replace(`/finance/commitments/${preview.commitment.id}`);
    } catch (e: any) {
      Alert.alert("Could not reserve", e?.message || "");
    } finally { setSaving(false); }
  };

  const keepDraft = () => {
    if (!preview?.commitment?.id) return;
    setReviewOpen(false);
    router.replace(`/finance/commitments/${preview.commitment.id}`);
  };

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
              <TextInput value={taskTitle} onChangeText={setTaskTitle} placeholder="e.g. Order laptop" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} testID="fc-task-title" />
              <Text style={styles.label}>Task due (optional)</Text>
              <DateTimeField mode="date" value={taskDue} onChange={setTaskDue} testID="fc-task-due" />
            </>
          )}

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <Pressable onPress={startAssessment} disabled={saving} style={[styles.cta, saving && { opacity: 0.5 }]} testID="fc-continue">
            <Text style={styles.ctaText}>{saving ? "Preparing…" : "Review reservation"}</Text>
          </Pressable>
          <Text style={styles.note}>Nothing is reserved until you confirm on the next screen.</Text>
        </ScrollView>
      </KeyboardAvoidingView>

      <CurrencyPickerModal visible={pickerOpen} selected={currency} onSelect={setCurrency} onClose={() => setPickerOpen(false)} />

      <Modal visible={reviewOpen} animationType="slide" transparent onRequestClose={keepDraft}>
        <View style={styles.sheetWrap}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Decision assessment</Text>
              <Pressable onPress={keepDraft} hitSlop={12} testID="fc-review-close"><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>Reserving this commitment will place a lien on your liquid money. It will not change Net Worth. You can complete, cancel, postpone or keep it active later.</Text>
            <View style={styles.factRow}><Text style={styles.factLabel}>Amount</Text><Text style={styles.factValue}>{preview?.commitment?.currency} {formatMoney(preview?.commitment?.amount || "0")}</Text></View>
            <View style={styles.factRow}><Text style={styles.factLabel}>Due</Text><Text style={styles.factValue}>{preview?.commitment?.due_date}</Text></View>
            <View style={styles.factRow}><Text style={styles.factLabel}>Priority</Text><Text style={styles.factValue}>{preview?.commitment?.priority}</Text></View>
            {(preview?.liquidity?.by_currency || []).filter((l: any) => l.currency === preview?.commitment?.currency).map((l: any) => (
              <View key={l.currency} style={styles.factRow}><Text style={styles.factLabel}>Current available (unreserved)</Text><Text style={styles.factValue}>{l.currency} {formatMoney(l.available_unreserved)}</Text></View>
            ))}
            <Pressable onPress={confirmReservation} disabled={saving} style={[styles.cta, saving && { opacity: 0.5 }]} testID="fc-confirm"><Text style={styles.ctaText}>Confirm & reserve</Text></Pressable>
            <Pressable onPress={keepDraft} style={styles.secondary} testID="fc-keep-draft"><Text style={styles.secondaryText}>Keep as draft</Text></Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.md, marginBottom: spacing.xs },
  help: { fontSize: 11, color: colors.onSurfaceSecondary },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  chipSel: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 13, color: colors.onBrandTertiary },
  chipTextSel: { color: colors.onBrandPrimary, fontWeight: "600" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.md },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", marginTop: spacing.lg },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center", borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  note: { textAlign: "center", fontSize: 11, color: colors.onSurfaceTertiary, marginTop: spacing.sm, fontStyle: "italic" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.sm },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  sheetBody: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  factRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.xs },
  factLabel: { fontSize: 13, color: colors.onSurfaceSecondary },
  factValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
});
