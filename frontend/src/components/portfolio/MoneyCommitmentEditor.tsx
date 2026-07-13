import { useMemo, useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import CurrencyPickerModal from "./CurrencyPickerModal";
import DateTimeField from "@/src/components/DateTimeField";
import {
  MONEY_COMMITMENT_PRESETS,
  MoneyCommitmentPreset,
  localMonthISO,
} from "@/src/lib/portfolio/constants";

export type MoneyCommitmentDraft = {
  id?: string;
  title: string;
  amount: string;
  currency: string;
  start_month: string;
  end_month: string | null;
  commitment_type: "income" | "expense" | "debt_payment" | "saving" | "investment";
  fixed_or_flexible: "fixed";
};

type Props = {
  visible: boolean;
  initial?: MoneyCommitmentDraft;
  defaultCurrency: string;
  onSubmit: (draft: MoneyCommitmentDraft) => Promise<void> | void;
  onClose: () => void;
};

// Helpers to bridge our HH:MM-only DateTimeField with a YYYY-MM picker. We
// present the month as YYYY-MM-01 in the picker and strip the day back off
// on save so the API sees the canonical YYYY-MM format.
const toDate = (m?: string | null) => (m ? `${m}-01` : "");
const toMonth = (d: string) => (d ? d.slice(0, 7) : "");

/**
 * Add / edit modal for a monthly_money_commitment. The user picks a preset
 * (Salary, Rent, etc.); commitment_type + fixed_or_flexible are derived from
 * the preset table. Currency defaults to the reporting currency but each
 * entry keeps its own.
 */
export default function MoneyCommitmentEditor({ visible, initial, defaultCurrency, onSubmit, onClose }: Props) {
  const grouped = useMemo(() => {
    const groups: Record<string, MoneyCommitmentPreset[]> = {};
    MONEY_COMMITMENT_PRESETS.forEach((p) => {
      if (!groups[p.group]) groups[p.group] = [];
      groups[p.group].push(p);
    });
    return groups;
  }, []);

  const findInitialPresetLabel = (): string => {
    if (!initial) return "Salary";
    // Match on both label AND commitment_type to disambiguate "Other Income"
    // vs "Other Fixed Expense" if two entries ever share a label.
    const p = MONEY_COMMITMENT_PRESETS.find(
      (x) => x.label === initial.title && x.commitment_type === initial.commitment_type,
    );
    return p ? p.label : (initial.title || "Salary");
  };

  const [presetLabel, setPresetLabel] = useState<string>(findInitialPresetLabel());
  const [customTitle, setCustomTitle] = useState<string>(
    // If the initial title doesn't match any preset (edited by hand later),
    // keep the custom label so we don't clobber the user's data.
    initial && !MONEY_COMMITMENT_PRESETS.some((x) => x.label === initial.title)
      ? initial.title
      : "",
  );
  const [amount, setAmount] = useState<string>(initial?.amount ?? "");
  const [currency, setCurrency] = useState<string>(initial?.currency || defaultCurrency || "USD");
  const [startMonth, setStartMonth] = useState<string>(initial?.start_month || localMonthISO());
  const [endMonth, setEndMonth] = useState<string>(initial?.end_month || "");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const activePreset =
    MONEY_COMMITMENT_PRESETS.find((p) => p.label === presetLabel) ||
    MONEY_COMMITMENT_PRESETS[0];

  const submit = async () => {
    setError(null);
    const title = customTitle.trim() || activePreset.label;
    if (!title) { setError("Title is required."); return; }
    const amt = (amount || "").trim();
    if (!amt) { setError("Amount is required."); return; }
    if (!/^\d+(\.\d+)?$/.test(amt)) { setError("Amount must be a positive decimal."); return; }
    if (!/^\d{4}-\d{2}$/.test(startMonth)) { setError("Start month must be YYYY-MM."); return; }
    if (endMonth && !/^\d{4}-\d{2}$/.test(endMonth)) { setError("End month must be YYYY-MM or empty."); return; }
    if (endMonth && endMonth < startMonth) { setError("End month must be on/after start month."); return; }
    setSaving(true);
    try {
      await onSubmit({
        id: initial?.id,
        title,
        amount: amt,
        currency,
        start_month: startMonth,
        end_month: endMonth || null,
        commitment_type: activePreset.commitment_type,
        fixed_or_flexible: activePreset.fixed_or_flexible,
      });
      onClose();
    } catch (e: any) {
      setError(e?.message || "Could not save commitment");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={12} testID="money-editor-close">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>{initial ? "Edit commitment" : "Add commitment"}</Text>
          <View style={{ width: 22 }} />
        </View>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {Object.keys(grouped).map((groupName) => (
              <View key={groupName}>
                <Text style={styles.section}>{groupName}</Text>
                <View style={styles.wrapRow}>
                  {grouped[groupName].map((p) => {
                    const sel = presetLabel === p.label;
                    return (
                      <Pressable
                        key={p.label}
                        onPress={() => setPresetLabel(p.label)}
                        style={[styles.chip, sel && styles.chipSel]}
                        testID={`money-preset-${p.commitment_type}-${p.label.replace(/\W+/g, "-").toLowerCase()}`}
                      >
                        <Text style={[styles.chipText, sel && styles.chipTextSel]}>{p.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}

            <Text style={styles.label}>Custom title (optional)</Text>
            <TextInput
              value={customTitle}
              onChangeText={setCustomTitle}
              style={styles.input}
              placeholder={activePreset.label}
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="money-editor-title"
            />

            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Amount</Text>
                <TextInput
                  value={amount}
                  onChangeText={(v) => setAmount(v.replace(/[^0-9.]/g, ""))}
                  keyboardType="decimal-pad"
                  style={styles.input}
                  placeholder="0"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID="money-editor-amount"
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Currency</Text>
                <Pressable
                  onPress={() => setPickerOpen(true)}
                  style={styles.input}
                  testID="money-editor-currency"
                >
                  <Text style={{ fontSize: 15, color: colors.onSurface }}>{currency}</Text>
                </Pressable>
              </View>
            </View>

            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Start month</Text>
                <DateTimeField mode="date" value={toDate(startMonth)} onChange={(v) => setStartMonth(toMonth(v))} testID="money-editor-start-month" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>End month (optional)</Text>
                <DateTimeField mode="date" value={toDate(endMonth)} onChange={(v) => setEndMonth(v ? toMonth(v) : "")} testID="money-editor-end-month" />
              </View>
            </View>

            {error && <Text style={styles.error} testID="money-editor-error">{error}</Text>}
          </ScrollView>
          <View style={styles.footer}>
            <Pressable
              style={[styles.cta, saving && { opacity: 0.5 }]}
              onPress={submit}
              disabled={saving}
              testID="money-editor-save"
            >
              <Text style={styles.ctaText}>{saving ? "Saving…" : "Save commitment"}</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>

        <CurrencyPickerModal
          visible={pickerOpen}
          selected={currency}
          onSelect={setCurrency}
          onClose={() => setPickerOpen(false)}
        />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.xxxl, paddingBottom: spacing.md,
  },
  title: { fontFamily: fonts.displayBold, fontSize: 16, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  section: { marginTop: spacing.md, fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 1, fontWeight: "600", marginBottom: spacing.xs },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface,
    justifyContent: "center",
  },
  wrapRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
  },
  chipSel: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 13, color: colors.onBrandTertiary },
  chipTextSel: { color: colors.onBrandPrimary, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xl, paddingTop: spacing.sm },
  cta: {
    backgroundColor: colors.onSurface, paddingVertical: spacing.lg,
    borderRadius: radius.pill, alignItems: "center",
  },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
