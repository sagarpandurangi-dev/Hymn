import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";

const LEARN_STATUSES = ["active", "archived"] as const;

type Props = {
  mode: "add" | "edit";
  initial?: {
    title: string;
    description: string;
    target_completion_date: string;
    status: string;
  } | null;
  onSubmit: (payload: { title: string; description: string; target_completion_date: string; status: string }) => Promise<void>;
  headerTitle: string;
  submitLabel: string;
  testIDPrefix: string;
};

export function LearningJourneyForm({ initial, onSubmit, headerTitle, submitLabel, testIDPrefix }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState(initial?.title || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [targetDate, setTargetDate] = useState(initial?.target_completion_date || "");
  const [status, setStatus] = useState<string>(initial?.status || "active");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    if (targetDate && !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      setError("Target date must be YYYY-MM-DD or empty.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit({
        title: title.trim(),
        description: description.trim(),
        target_completion_date: targetDate.trim(),
        status,
      });
    } catch (e: any) {
      setError(e?.message || "Could not save");
    } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID={`${testIDPrefix}-cancel`} hitSlop={12}>
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{headerTitle}</Text>
        <View style={{ width: 56 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Title</Text>
          <TextInput
            style={styles.titleInput}
            value={title}
            onChangeText={setTitle}
            placeholder="What do you want to learn?"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`${testIDPrefix}-title-input`}
          />

          <Text style={styles.label}>Description</Text>
          <TextInput
            style={styles.notes}
            value={description}
            onChangeText={setDescription}
            multiline
            textAlignVertical="top"
            placeholder="Why does this matter to you?"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`${testIDPrefix}-description-input`}
          />

          <Text style={styles.label}>Target completion date</Text>
          <DateTimeField
            mode="date"
            value={targetDate}
            onChange={setTargetDate}
            placeholder="Choose date (optional)"
            clearable
            testID={`${testIDPrefix}-target-date-input`}
          />

          {initial ? (
            <>
              <Text style={styles.label}>Status</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
                {LEARN_STATUSES.map((s) => {
                  const sel = status === s;
                  return (
                    <Pressable
                      key={s}
                      onPress={() => setStatus(s)}
                      style={[styles.chip, sel && styles.chipSelected]}
                      testID={`${testIDPrefix}-status-chip-${s}`}
                    >
                      <Text style={[styles.chipText, sel && styles.chipTextSelected, { textTransform: "capitalize" }]}>{s}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </>
          ) : null}

          {error ? <Text style={styles.errorText} testID={`${testIDPrefix}-error`}>{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={save} disabled={busy} testID={`${testIDPrefix}-save-button`}>
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={styles.ctaText}>{submitLabel}</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export default function AddLearningJourneyScreen() {
  const router = useRouter();
  return (
    <LearningJourneyForm
      mode="add"
      headerTitle="New journey"
      submitLabel="Start journey"
      testIDPrefix="add-learn"
      onSubmit={async (payload) => {
        await api.createLearningJourney({
          title: payload.title,
          description: payload.description,
          target_completion_date: payload.target_completion_date,
        });
        router.back();
      }}
    />
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  titleInput: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 100 },
  chipRow: { gap: spacing.sm, paddingRight: spacing.xl },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  chipSelected: { backgroundColor: colors.brandPrimary },
  chipText: { color: colors.onBrandTertiary, fontSize: 13, fontWeight: "500" },
  chipTextSelected: { color: colors.onBrandPrimary },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
