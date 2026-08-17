/**
 * Recurrence sheet — shared UI for configuring a task's recurrence.
 *
 * Design notes
 * ------------
 * • Bottom-sheet modal to stay inside the existing task detail flow.
 * • Cadence picker (chip row) with human-friendly labels.
 * • End condition: never / until date / N occurrences.
 * • Optional "pre-generate next N" toggle (option B). Default 0 = auto-spawn.
 * • The sheet is purely presentational — it hands a validated
 *   `RecurrenceSpec` to the caller via `onSave` and lets the caller decide
 *   which endpoint to hit (setTaskRecurrence vs updateTask.recurrence).
 */

import { useEffect, useState } from "react";
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing } from "@/src/lib/theme";
import type { RecurrenceSpec, RecurrenceCadence } from "@/src/lib/api";

// ---------------------------------------------------------------------------
// Vocabulary — kept in sync with backend/recurrence.py.
// ---------------------------------------------------------------------------
export const CADENCE_OPTIONS: { value: RecurrenceCadence; label: string; hint: string }[] = [
  { value: "daily",         label: "Daily",         hint: "Every day" },
  { value: "alternate_day", label: "Alternate day", hint: "Every 2 days" },
  { value: "weekly",        label: "Weekly",        hint: "Every 7 days" },
  { value: "fortnightly",   label: "Fortnightly",   hint: "Every 14 days" },
  { value: "monthly",       label: "Monthly",       hint: "Same calendar day each month" },
  { value: "quarterly",     label: "Quarterly",     hint: "Every 3 months" },
  { value: "half_yearly",   label: "Half-yearly",   hint: "Every 6 months" },
  { value: "yearly",        label: "Yearly",        hint: "Same date each year" },
];

const CADENCE_LABEL: Record<RecurrenceCadence, string> = Object.fromEntries(
  CADENCE_OPTIONS.map((o) => [o.value, o.label]),
) as Record<RecurrenceCadence, string>;

export const recurrenceLabel = (c?: RecurrenceCadence | null): string =>
  c ? CADENCE_LABEL[c] : "";

// ---------------------------------------------------------------------------
// Sheet component
// ---------------------------------------------------------------------------
export type RecurrenceSheetProps = {
  visible: boolean;
  initial?: RecurrenceSpec | null;
  /** Default anchor when the user hasn't customised one yet (usually the task due_date). */
  fallbackAnchor?: string;
  onClose: () => void;
  onSave: (spec: RecurrenceSpec) => Promise<void> | void;
  onClear?: () => Promise<void> | void;
  testID?: string;
};

export default function RecurrenceSheet({
  visible,
  initial,
  fallbackAnchor,
  onClose,
  onSave,
  onClear,
  testID,
}: RecurrenceSheetProps) {
  const [cadence, setCadence] = useState<RecurrenceCadence>(initial?.cadence || "weekly");
  const [anchor, setAnchor] = useState<string>(initial?.anchor_date || fallbackAnchor || todayIso());
  const [endType, setEndType] = useState<"never" | "until" | "count">(initial?.end_type || "never");
  const [endDate, setEndDate] = useState<string>(initial?.end_date || "");
  const [occurrenceCount, setOccurrenceCount] = useState<string>(
    initial?.occurrences_remaining != null ? String(initial.occurrences_remaining) : "",
  );
  const [preGen, setPreGen] = useState<boolean>((initial?.pre_generate_count || 0) > 0);
  const [preCount, setPreCount] = useState<string>(
    initial?.pre_generate_count ? String(initial.pre_generate_count) : "4",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Rehydrate state whenever the sheet reopens with different `initial`.
  useEffect(() => {
    if (!visible) return;
    setCadence(initial?.cadence || "weekly");
    setAnchor(initial?.anchor_date || fallbackAnchor || todayIso());
    setEndType(initial?.end_type || "never");
    setEndDate(initial?.end_date || "");
    setOccurrenceCount(initial?.occurrences_remaining != null ? String(initial.occurrences_remaining) : "");
    setPreGen((initial?.pre_generate_count || 0) > 0);
    setPreCount(initial?.pre_generate_count ? String(initial.pre_generate_count) : "4");
    setError(null);
  }, [visible, initial, fallbackAnchor]);

  const validate = (): RecurrenceSpec | null => {
    if (!isIsoDate(anchor)) { setError("Anchor date must be YYYY-MM-DD."); return null; }
    if (endType === "until") {
      if (!isIsoDate(endDate)) { setError("End date must be YYYY-MM-DD."); return null; }
      if (endDate < anchor) { setError("End date must be on or after anchor date."); return null; }
    }
    let occ: number | null = null;
    if (endType === "count") {
      const n = parseInt(occurrenceCount, 10);
      if (!Number.isFinite(n) || n <= 0) { setError("Occurrences must be a positive whole number."); return null; }
      occ = n;
    }
    let pre = 0;
    if (preGen) {
      const n = parseInt(preCount, 10);
      if (!Number.isFinite(n) || n <= 0) { setError("Pre-generate count must be positive."); return null; }
      pre = Math.min(12, n);
    }
    setError(null);
    return {
      cadence,
      anchor_date: anchor,
      end_type: endType,
      end_date: endType === "until" ? endDate : null,
      occurrences_remaining: occ,
      pre_generate_count: pre,
      series_id: initial?.series_id || undefined,
    };
  };

  const save = async () => {
    const spec = validate();
    if (!spec) return;
    setSaving(true);
    try { await onSave(spec); onClose(); }
    catch (e: any) { setError(e?.message || "Could not save recurrence"); }
    finally { setSaving(false); }
  };

  const clear = async () => {
    if (!onClear) return;
    setSaving(true);
    try { await onClear(); onClose(); }
    catch (e: any) { setError(e?.message || "Could not remove recurrence"); }
    finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.wrap}>
        <View style={styles.card} testID={testID}>
          <View style={styles.head}>
            <Text style={styles.title}>Recurrence</Text>
            <Pressable onPress={onClose} hitSlop={12} testID="rec-close"><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
          </View>
          <ScrollView style={{ maxHeight: 560 }} contentContainerStyle={{ gap: spacing.md }} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>FREQUENCY</Text>
            <View style={styles.chipRow}>
              {CADENCE_OPTIONS.map((opt) => (
                <Pressable
                  key={opt.value}
                  onPress={() => setCadence(opt.value)}
                  style={[styles.chip, cadence === opt.value && styles.chipSel]}
                  testID={`rec-cadence-${opt.value}`}
                >
                  <Text style={[styles.chipText, cadence === opt.value && styles.chipTextSel]}>{opt.label}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.hint}>{CADENCE_OPTIONS.find((o) => o.value === cadence)?.hint}</Text>

            <Text style={styles.label}>ANCHOR DATE</Text>
            <TextInput
              value={anchor}
              onChangeText={setAnchor}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
              testID="rec-anchor"
            />
            <Text style={styles.hint}>All future occurrences are computed from this date.</Text>

            <Text style={styles.label}>ENDS</Text>
            <View style={styles.chipRow}>
              {[
                { v: "never" as const, l: "Never" },
                { v: "until" as const, l: "On date" },
                { v: "count" as const, l: "After N times" },
              ].map((o) => (
                <Pressable
                  key={o.v}
                  onPress={() => setEndType(o.v)}
                  style={[styles.chipSm, endType === o.v && styles.chipSel]}
                  testID={`rec-end-${o.v}`}
                >
                  <Text style={[styles.chipTextSm, endType === o.v && styles.chipTextSel]}>{o.l}</Text>
                </Pressable>
              ))}
            </View>
            {endType === "until" ? (
              <TextInput
                value={endDate}
                onChangeText={setEndDate}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                testID="rec-end-date"
              />
            ) : null}
            {endType === "count" ? (
              <TextInput
                value={occurrenceCount}
                onChangeText={setOccurrenceCount}
                keyboardType="number-pad"
                placeholder="e.g. 12"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                testID="rec-end-count"
              />
            ) : null}

            <View style={styles.switchRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>PRE-GENERATE NEXT OCCURRENCES</Text>
                <Text style={styles.hint}>Off: next task is spawned when this one is completed. On: create a rolling window of upcoming tasks now.</Text>
              </View>
              <Switch value={preGen} onValueChange={setPreGen} testID="rec-pre-toggle" />
            </View>
            {preGen ? (
              <TextInput
                value={preCount}
                onChangeText={setPreCount}
                keyboardType="number-pad"
                placeholder="4"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                testID="rec-pre-count"
              />
            ) : null}

            {error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>

          <View style={styles.actions}>
            {onClear && initial ? (
              <Pressable onPress={clear} style={[styles.secondary, styles.danger]} disabled={saving} testID="rec-clear">
                <Text style={styles.dangerText}>Remove</Text>
              </Pressable>
            ) : null}
            <Pressable onPress={save} disabled={saving} style={[styles.primary, saving && { opacity: 0.5 }]} testID="rec-save">
              <Text style={styles.primaryText}>{saving ? "Saving…" : (initial ? "Update recurrence" : "Make recurring")}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function todayIso(): string {
  const d = new Date();
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function isIsoDate(s: string): boolean {
  if (!s || s.length !== 10 || s[4] !== "-" || s[7] !== "-") return false;
  const [y, m, d] = s.split("-").map((x) => parseInt(x, 10));
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return false;
  return m >= 1 && m <= 12 && d >= 1 && d <= 31;
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  card: { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 20, fontWeight: "700", color: colors.onSurface },
  label: { fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 1.4, fontWeight: "700", marginTop: spacing.sm },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, lineHeight: 17 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipSm: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipSel: { backgroundColor: colors.onSurface, borderColor: colors.onSurface },
  chipText: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  chipTextSm: { fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  chipTextSel: { color: colors.onSurfaceInverse },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: 10, paddingHorizontal: spacing.md, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface, borderWidth: 1, borderColor: colors.border },
  switchRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.sm },
  error: { color: colors.error, fontSize: 13, marginTop: 4 },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  primary: { flex: 1, backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: 999, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700", letterSpacing: 0.3 },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.xl, borderRadius: 999, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  danger: { borderColor: colors.error },
  dangerText: { color: colors.error, fontSize: 14, fontWeight: "700" },
});
