import { useEffect, useState } from "react";
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
  DAYS_OF_WEEK,
  DAY_LABELS,
  DayOfWeek,
  FLEXIBILITY_OPTIONS,
  TIME_CATEGORIES,
  hhmmToMinutes,
  hasOverlapOnDay,
  isCrossMidnight,
  nextDay,
  splitCrossMidnight,
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

type ExistingByDay = Record<DayOfWeek, TimeBlockDraft[]>;

type SubmitPayload = {
  id?: string;
  title: string;
  commitment_type: string;
  flexibility: "fixed" | "flexible";
  /** One entry per record to persist. Cross-midnight blocks emit 2 entries per selected day. */
  entries: { day: DayOfWeek; start_time: string; end_time: string }[];
};

type Props = {
  visible: boolean;
  day: DayOfWeek;
  initial?: TimeBlockDraft;
  /** All same-day blocks (per weekday) keyed by day-of-week for overlap checks. */
  existingByDay: ExistingByDay;
  onSubmit: (payload: SubmitPayload) => Promise<void> | void;
  onClose: () => void;
};

/**
 * Add / edit modal for time_commitment blocks. Two extensions over the base
 * form:
 *
 *  1. Multi-day: users may select any subset of weekdays; the same start/end
 *     times are seeded onto each selected day when saving. Editing an
 *     existing block is single-day (no cloning) to avoid surprising deletes.
 *
 *  2. Cross-midnight: end_time may be earlier than start_time (e.g. sleep
 *     23:30 → 06:30). We surface an inline hint AND split each selected day
 *     into two records — the "night" half ends at 24:00 on day D and the
 *     "morning" half starts at 00:00 on day D+1.
 */
export default function TimeBlockEditor({ visible, day, initial, existingByDay, onSubmit, onClose }: Props) {
  const [title, setTitle] = useState(initial?.title || "");
  const [startTime, setStartTime] = useState(initial?.start_time || "09:00");
  const [endTime, setEndTime] = useState(initial?.end_time || "10:00");
  const [category, setCategory] = useState<string>(initial?.commitment_type || "work");
  const [flex, setFlex] = useState<"fixed" | "flexible">(initial?.flexibility || "flexible");
  // When editing, the multi-day selector is locked to the block's original day.
  const [selectedDays, setSelectedDays] = useState<DayOfWeek[]>(
    initial ? [day] : [day],
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The Modal keeps this component mounted between open/close cycles, so
  // useState initial values are only applied once. Whenever the modal is
  // (re)opened with different `initial` / `day` inputs we need to reseed the
  // form so add-vs-edit switches don't show stale data from the previous
  // session.
  useEffect(() => {
    if (!visible) return;
    setTitle(initial?.title || "");
    setStartTime(initial?.start_time || "09:00");
    setEndTime(initial?.end_time || "10:00");
    setCategory(initial?.commitment_type || "work");
    setFlex(initial?.flexibility || "flexible");
    setSelectedDays([day]);
    setError(null);
    setSaving(false);
  }, [visible, initial, day]);

  const wraps = isCrossMidnight(startTime, endTime);
  const editing = !!initial;

  const toggleDay = (d: DayOfWeek) => {
    if (editing) return;  // one-day edits only
    setSelectedDays((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d],
    );
  };

  const submit = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    const timeErr = validateBlockTimes(startTime, endTime);
    if (timeErr) { setError(timeErr); return; }
    if (selectedDays.length === 0) { setError("Select at least one day."); return; }

    // Pre-flight overlap check per selected day, taking cross-midnight into
    // account. When a block wraps, both the "night" half AND the "morning"
    // half must fit their respective days without overlapping existing
    // records. `initial.id` is treated as the block being replaced so we
    // don't self-collide during an edit.
    for (const d of selectedDays) {
      const pieces = splitCrossMidnight(d, startTime, endTime);
      for (const p of pieces) {
        const same = existingByDay[p.day] || [];
        if (hasOverlapOnDay(same, { id: initial?.id, start_time: p.start_time, end_time: p.end_time })) {
          setError(`Overlaps another block on ${DAY_LABELS[p.day]}.`);
          return;
        }
      }
    }

    // Build final entries list: one splitCrossMidnight per selected day.
    const entries: SubmitPayload["entries"] = [];
    for (const d of selectedDays) {
      for (const p of splitCrossMidnight(d, startTime, endTime)) {
        entries.push(p);
      }
    }

    setSaving(true);
    try {
      await onSubmit({
        id: initial?.id,
        title: title.trim(),
        commitment_type: category,
        flexibility: flex,
        entries,
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
          <Text style={styles.title}>{initial ? "Edit block" : "Add block"}</Text>
          <View style={{ width: 22 }} />
        </View>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Title</Text>
            <TextInput
              value={title}
              onChangeText={setTitle}
              style={styles.input}
              placeholder="e.g. Deep work, Sleep"
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
            {wraps && (
              <Text style={styles.info} testID="time-block-crossmidnight-info">
                Crosses midnight — will be saved as two blocks (
                {selectedDays.map((d) => DAY_LABELS[d]).join(", ")} → {selectedDays.map((d) => DAY_LABELS[nextDay(d)]).join(", ")}).
              </Text>
            )}

            <Text style={styles.label}>Apply to days</Text>
            <View style={styles.wrapRow}>
              {DAYS_OF_WEEK.map((d) => {
                const sel = selectedDays.includes(d);
                return (
                  <Pressable
                    key={d}
                    onPress={() => toggleDay(d)}
                    style={[styles.chip, sel && styles.chipSel, editing && !sel && { opacity: 0.4 }]}
                    disabled={editing && !sel}
                    testID={`time-block-day-${d}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{DAY_LABELS[d].slice(0, 3)}</Text>
                  </Pressable>
                );
              })}
            </View>
            {editing && (
              <Text style={styles.info}>Editing keeps this block on its original day. Delete and re-add to move it.</Text>
            )}

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

// Suppress unused import — `hhmmToMinutes` was previously used and may be
// helpful again as validation grows.
void hhmmToMinutes;

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
  info: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs, fontStyle: "italic" },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xl, paddingTop: spacing.sm },
  cta: {
    backgroundColor: colors.onSurface, paddingVertical: spacing.lg,
    borderRadius: radius.pill, alignItems: "center",
  },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
