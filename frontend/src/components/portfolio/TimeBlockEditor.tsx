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
import DateTimeField from "@/src/components/DateTimeField";
import {
  DAY_LABELS,
  DayOfWeek,
  FLEXIBILITY_OPTIONS,
  TIME_CATEGORIES,
  hasOverlapOnDay,
  validateBlockTimes,
} from "@/src/lib/portfolio/constants";

export type TimeBlockDraft = {
  id?: string;
  title: string;
  start_time: string;
  end_time: string;
  commitment_type: string;
  flexibility: "fixed" | "flexible";
};

type Props = {
  visible: boolean;
  day: DayOfWeek;
  initial?: TimeBlockDraft;
  existing: TimeBlockDraft[];  // Same-day blocks for overlap check.
  onSubmit: (draft: Required<Pick<TimeBlockDraft, "title" | "start_time" | "end_time" | "commitment_type" | "flexibility">> & { id?: string }) => Promise<void> | void;
  onClose: () => void;
};

/**
 * Add / edit modal for a single time_commitment block. All time validation
 * (HH:MM, end > start, no cross-midnight, no zero-duration, no overlap) is
 * performed inline so the user gets immediate feedback before the API call.
 */
export default function TimeBlockEditor({ visible, day, initial, existing, onSubmit, onClose }: Props) {
  const [title, setTitle] = useState(initial?.title || "");
  const [startTime, setStartTime] = useState(initial?.start_time || "09:00");
  const [endTime, setEndTime] = useState(initial?.end_time || "10:00");
  const [category, setCategory] = useState<string>(initial?.commitment_type || "work");
  const [flex, setFlex] = useState<"fixed" | "flexible">(initial?.flexibility || "flexible");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    const timeErr = validateBlockTimes(startTime, endTime);
    if (timeErr) { setError(timeErr); return; }
    if (hasOverlapOnDay(existing, { id: initial?.id, start_time: startTime, end_time: endTime })) {
      setError("Overlaps another block on the same day.");
      return;
    }
    setSaving(true);
    try {
      await onSubmit({
        id: initial?.id,
        title: title.trim(),
        start_time: startTime,
        end_time: endTime,
        commitment_type: category,
        flexibility: flex,
      });
      onClose();
    } catch (e: any) {
      setError(e?.message || "Could not save block");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.wrap}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={12} testID="time-block-close">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>{initial ? "Edit block" : "Add block"} · {DAY_LABELS[day]}</Text>
          <View style={{ width: 22 }} />
        </View>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Title</Text>
            <TextInput
              value={title}
              onChangeText={setTitle}
              style={styles.input}
              placeholder="e.g. Deep work, School run"
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="time-block-title"
            />

            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Start</Text>
                <DateTimeField mode="time" value={startTime} onChange={setStartTime} testID="time-block-start" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>End</Text>
                <DateTimeField mode="time" value={endTime} onChange={setEndTime} testID="time-block-end" />
              </View>
            </View>

            <Text style={styles.label}>Category</Text>
            <View style={styles.wrapRow}>
              {TIME_CATEGORIES.map((c) => {
                const sel = category === c.code;
                return (
                  <Pressable
                    key={c.code}
                    onPress={() => setCategory(c.code)}
                    style={[styles.chip, sel && styles.chipSel]}
                    testID={`time-block-cat-${c.code}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{c.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.label}>Flexibility</Text>
            <View style={styles.wrapRow}>
              {FLEXIBILITY_OPTIONS.map((f) => {
                const sel = flex === f.code;
                return (
                  <Pressable
                    key={f.code}
                    onPress={() => setFlex(f.code)}
                    style={[styles.chip, sel && styles.chipSel]}
                    testID={`time-block-flex-${f.code}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{f.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            {error && <Text style={styles.error} testID="time-block-error">{error}</Text>}
          </ScrollView>
          <View style={styles.footer}>
            <Pressable
              style={[styles.cta, saving && { opacity: 0.5 }]}
              onPress={submit}
              disabled={saving}
              testID="time-block-save"
            >
              <Text style={styles.ctaText}>{saving ? "Saving…" : "Save block"}</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
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
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface,
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
