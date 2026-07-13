import { useState } from "react";
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
import {
  ACCOUNT_PRESETS,
  ACCOUNT_PRESET_BY_CODE,
} from "@/src/lib/portfolio/constants";

export type AccountDraft = {
  id?: string;
  account_type: string;
  name: string;
  currency: string;
  current_value: string;
};

type Props = {
  visible: boolean;
  initial?: AccountDraft;
  defaultCurrency: string;
  onSubmit: (draft: AccountDraft) => Promise<void> | void;
  onClose: () => void;
};

/**
 * Add / edit modal for a financial_account. The user picks Account Type, Name,
 * Currency, and Current Value; liquidity_type + fixed_or_flexible fall out
 * from ACCOUNT_PRESETS and are attached at submit time.
 */
export default function AccountEditor({ visible, initial, defaultCurrency, onSubmit, onClose }: Props) {
  const [type, setType] = useState<string>(initial?.account_type || "cash");
  const [name, setName] = useState(initial?.name || "");
  const [currency, setCurrency] = useState(initial?.currency || defaultCurrency || "USD");
  const [value, setValue] = useState(initial?.current_value ?? "0");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const assets = ACCOUNT_PRESETS.filter((p) => p.kind === "asset");
  const liabilities = ACCOUNT_PRESETS.filter((p) => p.kind === "liability");

  const submit = async () => {
    setError(null);
    if (!ACCOUNT_PRESET_BY_CODE[type]) { setError("Pick an account type."); return; }
    if (!name.trim()) { setError("Name is required."); return; }
    // Amount is stored as a decimal string; empty -> reject; negatives -> reject.
    const cleaned = (value || "").trim();
    if (!cleaned) { setError("Current value is required."); return; }
    if (!/^\d+(\.\d+)?$/.test(cleaned)) { setError("Current value must be a positive decimal."); return; }
    setSaving(true);
    try {
      await onSubmit({
        id: initial?.id,
        account_type: type,
        name: name.trim(),
        currency,
        current_value: cleaned,
      });
      onClose();
    } catch (e: any) {
      setError(e?.message || "Could not save account");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={12} testID="account-editor-close">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>{initial ? "Edit account" : "Add account"}</Text>
          <View style={{ width: 22 }} />
        </View>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <Text style={styles.section}>Assets</Text>
            <View style={styles.wrapRow}>
              {assets.map((p) => {
                const sel = type === p.code;
                return (
                  <Pressable
                    key={p.code}
                    onPress={() => setType(p.code)}
                    style={[styles.chip, sel && styles.chipSel]}
                    testID={`account-type-${p.code}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{p.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.section}>Liabilities</Text>
            <View style={styles.wrapRow}>
              {liabilities.map((p) => {
                const sel = type === p.code;
                return (
                  <Pressable
                    key={p.code}
                    onPress={() => setType(p.code)}
                    style={[styles.chip, sel && styles.chipSel]}
                    testID={`account-type-${p.code}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{p.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.label}>Name</Text>
            <TextInput
              value={name}
              onChangeText={setName}
              style={styles.input}
              placeholder="e.g. HDFC Savings, Fidelity IRA"
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="account-name"
            />

            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Currency</Text>
                <Pressable
                  onPress={() => setPickerOpen(true)}
                  style={styles.input}
                  testID="account-currency"
                >
                  <Text style={{ fontSize: 15, color: colors.onSurface }}>{currency}</Text>
                </Pressable>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Current value</Text>
                <TextInput
                  value={value}
                  onChangeText={(v) => setValue(v.replace(/[^0-9.]/g, ""))}
                  keyboardType="decimal-pad"
                  style={styles.input}
                  placeholder="0"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID="account-value"
                />
              </View>
            </View>

            {error && <Text style={styles.error} testID="account-editor-error">{error}</Text>}
          </ScrollView>
          <View style={styles.footer}>
            <Pressable
              style={[styles.cta, saving && { opacity: 0.5 }]}
              onPress={submit}
              disabled={saving}
              testID="account-editor-save"
            >
              <Text style={styles.ctaText}>{saving ? "Saving…" : "Save account"}</Text>
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
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  section: { marginTop: spacing.md, fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 1, fontWeight: "600" },
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
