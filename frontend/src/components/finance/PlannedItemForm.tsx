/**
 * Add / edit / view a Planned money item. Used by the Planned money screen
 * and the Finance tab's "+ New" button.
 *
 * - editable items: full form + Mark done + Delete
 * - editable === false: read-only summary with "Open in older screen"
 */
import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { api, ApiError, PlannedItem, PlannedItemInput, PlannedPurpose, PlannedRepeat } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";
import { confirmAction } from "@/src/lib/confirm";

const OUT_TYPES: { value: PlannedPurpose; label: string }[] = [
  { value: "spend", label: "Spend" },
  { value: "saving", label: "Saving" },
  { value: "investment", label: "Investment" },
  { value: "loan_payment", label: "Loan payment" },
  { value: "other", label: "Other" },
];
const REPEATS: { value: PlannedRepeat; label: string }[] = [
  { value: "once", label: "Once" },
  { value: "monthly", label: "Monthly" },
  { value: "yearly", label: "Yearly" },
];
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const plannedWhen = (it: PlannedItem) =>
  it.repeat === "monthly" ? "Monthly" : it.repeat === "yearly" ? "Yearly" : it.date ? dateLabel(it.date) : "";
export const plannedSigned = (it: PlannedItem) =>
  `${it.direction === "in" ? "+" : "−"}${formatMoney(String(it.amount))}`;

/** Where a read-only (older) item lives. */
function olderScreen(it: PlannedItem): string | null {
  if (it.source === "monthly_commitment") return `/finance/monthly?currency=${encodeURIComponent(it.currency)}`;
  if (it.source === "financial_commitment") return `/finance/commitments/${it.id}`;
  if (it.source === "expected_income") return "/finance/expected-income";
  return null;
}

function Chip({ label, selected, onPress, testID }: { label: string; selected: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, selected && styles.chipSel]} testID={testID}>
      <Text style={[styles.chipText, selected && styles.chipTextSel]}>{label}</Text>
    </Pressable>
  );
}

type Props = {
  visible: boolean;
  /** null = add a new item */
  item: PlannedItem | null;
  defaultCurrency: string;
  onClose: () => void;
  onSaved: () => void;
};

export default function PlannedItemForm({ visible, item, defaultCurrency, onClose, onSaved }: Props) {
  const router = useRouter();
  const readOnly = !!item && item.editable === false;
  const [title, setTitle] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [purpose, setPurpose] = useState<PlannedPurpose>("spend");
  const [amount, setAmount] = useState("");
  const [repeat, setRepeat] = useState<PlannedRepeat>("once");
  const [date, setDate] = useState("");
  const [startMonth, setStartMonth] = useState("");
  const [endMonth, setEndMonth] = useState("");
  const [maybe, setMaybe] = useState(false);
  const [setAside, setSetAside] = useState(false);
  const [busy, setBusy] = useState<"save" | "done" | "delete" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!visible) return;
    setError("");
    setBusy(null);
    setTitle(item?.title ?? "");
    setDirection(item?.direction ?? "out");
    setPurpose(item?.purpose ?? "spend");
    setAmount(item ? String(item.amount ?? "") : "");
    setRepeat(item?.repeat ?? "once");
    setDate(item?.date ?? "");
    setStartMonth(item?.start_month ?? "");
    setEndMonth(item?.end_month ?? "");
    setMaybe(item?.certainty === "maybe");
    setSetAside(!!item?.set_aside);
  }, [visible, item]);

  const isOneOffSpend = direction === "out" && purpose === "spend" && repeat === "once";

  const save = async () => {
    if (busy) return;
    const name = title.trim();
    const amt = amount.trim().replace(/,/g, "");
    if (!name) { setError("Enter a name."); return; }
    if (!amt || !/^\d+(\.\d{1,2})?$/.test(amt) || Number(amt) <= 0) { setError("Enter an amount greater than 0."); return; }
    if (repeat === "once" && !DATE_RE.test(date)) { setError("Choose a date."); return; }
    if (repeat !== "once") {
      if (!MONTH_RE.test(startMonth.trim())) { setError("Enter a start month as YYYY-MM."); return; }
      if (endMonth.trim() && !MONTH_RE.test(endMonth.trim())) { setError("Enter the end month as YYYY-MM, or leave it empty."); return; }
    }
    const payload: PlannedItemInput = {
      title: name,
      direction,
      purpose: direction === "in" ? "income" : purpose,
      amount: amt,
      currency: item?.currency || defaultCurrency,
      repeat,
      date: repeat === "once" ? date : null,
      start_month: repeat === "once" ? null : startMonth.trim(),
      end_month: repeat === "once" ? null : endMonth.trim() || null,
      certainty: maybe ? "maybe" : "sure",
      set_aside: isOneOffSpend ? setAside : false,
    };
    setBusy("save");
    setError("");
    try {
      if (item) await api.updatePlannedMoney(item.id, payload);
      else await api.createPlannedMoney(payload);
      onSaved();
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  };

  const markDone = async () => {
    if (!item || busy) return;
    setBusy("done");
    setError("");
    try {
      await api.updatePlannedMoney(item.id, { status: "done" });
      onSaved();
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!item || busy) return;
    const ok = await confirmAction("Delete this item?", `"${item.title}" will be removed from planned money.`, "Delete");
    if (!ok) return;
    setBusy("delete");
    setError("");
    try {
      await api.deletePlannedMoney(item.id);
      onSaved();
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  };

  const older = item ? olderScreen(item) : null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={() => !busy && onClose()}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.backdrop}>
        <View style={styles.sheet}>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            <Text style={styles.title}>{readOnly ? item?.title : item ? "Edit planned money" : "Add planned money"}</Text>

            {readOnly && item ? (
              <>
                <Text style={styles.note} testID="planned-older-note">From an older screen</Text>
                <View style={styles.roRow}><Text style={styles.roLabel}>Amount</Text><Text style={styles.roValue}>{item.currency} {plannedSigned(item)}</Text></View>
                <View style={styles.roRow}><Text style={styles.roLabel}>When</Text><Text style={styles.roValue}>{plannedWhen(item) || "—"}</Text></View>
                {item.status ? <View style={styles.roRow}><Text style={styles.roLabel}>Status</Text><Text style={styles.roValue}>{item.status}</Text></View> : null}
                {older ? (
                  <Pressable style={styles.primary} onPress={() => { onClose(); router.push(older as any); }} testID="planned-open-older">
                    <Text style={styles.primaryText}>Open in older screen</Text>
                  </Pressable>
                ) : null}
                <Pressable style={styles.secondary} onPress={onClose} testID="planned-close">
                  <Text style={styles.secondaryText}>Close</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Text style={styles.label}>Name</Text>
                <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="e.g. Rent" placeholderTextColor={financeColors.inkFaint} testID="planned-name-input" />

                <Text style={styles.label}>In / Out</Text>
                <View style={styles.chips}>
                  <Chip label="In" selected={direction === "in"} onPress={() => { setDirection("in"); setPurpose("income"); }} testID="planned-direction-in" />
                  <Chip label="Out" selected={direction === "out"} onPress={() => { setDirection("out"); if (purpose === "income") setPurpose("spend"); }} testID="planned-direction-out" />
                </View>

                <Text style={styles.label}>Type</Text>
                {direction === "in" ? (
                  <View style={styles.chips}><Chip label="Income" selected onPress={() => undefined} testID="planned-type-income" /></View>
                ) : (
                  <View style={styles.chips}>
                    {OUT_TYPES.map((t) => (
                      <Chip key={t.value} label={t.label} selected={purpose === t.value} onPress={() => setPurpose(t.value)} testID={`planned-type-${t.value}`} />
                    ))}
                  </View>
                )}

                <Text style={styles.label}>Amount ({item?.currency || defaultCurrency})</Text>
                <TextInput style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={financeColors.inkFaint} testID="planned-amount-input" />

                <Text style={styles.label}>Repeats</Text>
                <View style={styles.chips}>
                  {REPEATS.map((r) => (
                    <Chip key={r.value} label={r.label} selected={repeat === r.value} onPress={() => setRepeat(r.value)} testID={`planned-repeat-${r.value}`} />
                  ))}
                </View>

                {repeat === "once" ? (
                  <>
                    <Text style={styles.label}>Date</Text>
                    <DateTimeField mode="date" value={date} onChange={setDate} testID="planned-date" />
                  </>
                ) : (
                  <View style={{ flexDirection: "row", gap: financeSpace.md }}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>Start month</Text>
                      <TextInput style={styles.input} value={startMonth} onChangeText={setStartMonth} placeholder="YYYY-MM" placeholderTextColor={financeColors.inkFaint} autoCapitalize="none" testID="planned-start-month" />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>End month (optional)</Text>
                      <TextInput style={styles.input} value={endMonth} onChangeText={setEndMonth} placeholder="YYYY-MM" placeholderTextColor={financeColors.inkFaint} autoCapitalize="none" testID="planned-end-month" />
                    </View>
                  </View>
                )}

                <View style={styles.switchRow}>
                  <Text style={styles.switchLabel}>Not sure yet</Text>
                  <Switch value={maybe} onValueChange={setMaybe} trackColor={{ false: financeColors.divider, true: financeColors.ink }} testID="planned-maybe-switch" />
                </View>
                {isOneOffSpend ? (
                  <View style={styles.switchRow}>
                    <Text style={styles.switchLabel}>Set money aside</Text>
                    <Switch value={setAside} onValueChange={setSetAside} trackColor={{ false: financeColors.divider, true: financeColors.ink }} testID="planned-set-aside-switch" />
                  </View>
                ) : null}

                {error ? <Text style={styles.error} testID="planned-form-error">{error}</Text> : null}

                <View style={styles.actions}>
                  <Pressable style={styles.secondary} onPress={onClose} disabled={!!busy} testID="planned-cancel">
                    <Text style={styles.secondaryText}>Cancel</Text>
                  </Pressable>
                  <Pressable style={[styles.primary, styles.flex1, !!busy && styles.disabled]} onPress={save} disabled={!!busy} testID="planned-save">
                    {busy === "save" ? <ActivityIndicator color="#FBFBF6" /> : <Text style={styles.primaryText}>Save</Text>}
                  </Pressable>
                </View>

                {item ? (
                  <View style={styles.actions}>
                    <Pressable style={[styles.secondary, styles.flex1, !!busy && styles.disabled]} onPress={markDone} disabled={!!busy || item.status === "done"} testID="planned-mark-done">
                      {busy === "done" ? <ActivityIndicator color={financeColors.ink} /> : <Text style={styles.secondaryText}>{item.status === "done" ? "Done" : "Mark done"}</Text>}
                    </Pressable>
                    <Pressable style={[styles.danger, styles.flex1, !!busy && styles.disabled]} onPress={remove} disabled={!!busy} testID="planned-delete">
                      {busy === "delete" ? <ActivityIndicator color={financeColors.negative} /> : <Text style={styles.dangerText}>Delete</Text>}
                    </Pressable>
                  </View>
                ) : null}
              </>
            )}
            {readOnly && error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheet: { backgroundColor: financeColors.card, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, maxHeight: "90%" },
  body: { padding: financeSpace.xl, gap: financeSpace.sm, paddingBottom: financeSpace.xxxl },
  title: { fontSize: 17, fontWeight: "700", color: financeColors.ink, marginBottom: financeSpace.xs },
  note: { fontSize: 12.5, color: financeColors.inkMuted, fontStyle: "italic" },
  label: { fontSize: 12, fontWeight: "600", color: financeColors.inkMuted, letterSpacing: 0.4, marginTop: financeSpace.sm },
  input: { borderWidth: 1, borderColor: financeColors.cardBorder, borderRadius: financeRadius.md, paddingHorizontal: financeSpace.md, minHeight: 48, fontSize: 15, color: financeColors.ink },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm },
  chip: { minHeight: 36, paddingHorizontal: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", justifyContent: "center" },
  chipSel: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipText: { fontSize: 13, color: financeColors.ink },
  chipTextSel: { color: "#FBFBF6", fontWeight: "700" },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44, marginTop: financeSpace.xs },
  switchLabel: { fontSize: 15, color: financeColors.ink },
  error: { fontSize: 13, color: financeColors.negative, marginTop: financeSpace.xs },
  actions: { flexDirection: "row", gap: financeSpace.md, marginTop: financeSpace.md },
  flex1: { flex: 1 },
  primary: { backgroundColor: financeColors.ink, minHeight: 48, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center", paddingHorizontal: financeSpace.lg, marginTop: financeSpace.sm },
  primaryText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700" },
  secondary: { minHeight: 48, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", justifyContent: "center", marginTop: financeSpace.sm },
  secondaryText: { color: financeColors.ink, fontSize: 14, fontWeight: "600" },
  danger: { minHeight: 48, borderRadius: financeRadius.pill, borderWidth: 1, borderColor: financeColors.negative, alignItems: "center", justifyContent: "center", marginTop: financeSpace.sm },
  dangerText: { color: financeColors.negative, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  roRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: financeSpace.xs },
  roLabel: { fontSize: 13, color: financeColors.inkMuted },
  roValue: { fontSize: 14, fontWeight: "600", color: financeColors.ink },
});
