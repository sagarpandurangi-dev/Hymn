import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing, CheckinCadence } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";
import ConfirmModal from "@/src/components/ConfirmModal";

const TOTAL_STEPS = 6;

const CADENCE_META: { key: CheckinCadence; label: string; blurb: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "daily", label: "Daily", blurb: "Check in every day.", icon: "sunny-outline" },
  { key: "weekly", label: "Weekly", blurb: "Check in every week.", icon: "calendar-outline" },
  { key: "monthly", label: "Monthly", blurb: "Check in every month.", icon: "calendar-number-outline" },
  { key: "manual", label: "Manual", blurb: "Check in when you want.", icon: "hand-left-outline" },
];

type WizardState = {
  title: string;
  why: string;
  targetDate: string;
  outcomeTitle: string;
  outcomeTarget: string;
  outcomeUnit: string;
  taskTitle: string;
  taskDueDate: string;
  cadence: CheckinCadence | "";
};

const initial: WizardState = {
  title: "",
  why: "",
  targetDate: "",
  outcomeTitle: "",
  outcomeTarget: "",
  outcomeUnit: "",
  taskTitle: "",
  taskDueDate: "",
  cadence: "",
};

function isStepValid(step: number, s: WizardState): boolean {
  switch (step) {
    case 1: return s.title.trim().length > 0;
    case 2: return s.why.trim().length > 0;
    case 3: return true; // target date is optional
    case 4: return s.outcomeTitle.trim().length > 0;
    case 5: return s.taskTitle.trim().length > 0;
    case 6: return !!s.cadence;
    default: return false;
  }
}

export default function KnowledgeWizardScreen() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [state, setState] = useState<WizardState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);

  const set = <K extends keyof WizardState>(k: K, v: WizardState[K]) => setState((p) => ({ ...p, [k]: v }));

  const canNext = isStepValid(step, state);

  const goNext = () => {
    setError(null);
    if (!canNext) return;
    if (step < TOTAL_STEPS) setStep(step + 1);
  };
  const goPrev = () => {
    setError(null);
    if (step > 1) setStep(step - 1);
  };

  const tryCancel = () => {
    // Only prompt if user has entered anything.
    const dirty = Object.values(state).some((v) => (typeof v === "string" ? v.trim().length > 0 : !!v));
    if (dirty) setCancelOpen(true);
    else router.back();
  };

  const submit = async () => {
    setError(null);
    if (!isStepValid(6, state) || !state.cadence) return;
    setBusy(true);
    try {
      const created = await api.createLearningJourney({
        title: state.title.trim(),
        why: state.why.trim(),
        target_completion_date: state.targetDate.trim(),
        first_outcome: {
          title: state.outcomeTitle.trim(),
          target_value: state.outcomeTarget.trim(),
          unit: state.outcomeUnit.trim(),
          outcome_type: "generic",
        },
        first_task: {
          title: state.taskTitle.trim(),
          due_date: state.taskDueDate.trim(),
          priority: "medium",
        },
        checkin_cadence: state.cadence,
      });
      router.replace(`/goals/${created.id}`);
    } catch (e: any) {
      setError(e?.message || "Could not create journey. Please retry.");
    } finally {
      setBusy(false);
    }
  };

  const stepTitle = ({
    1: "What do you want to learn?",
    2: "Why does this matter?",
    3: "By when?",
    4: "First expected outcome",
    5: "First task",
    6: "Check-in cadence",
  } as Record<number, string>)[step];

  const stepSub = ({
    1: "Give your learning journey a clear title.",
    2: "A single reason keeps you honest.",
    3: "Optional. Choose a target completion date.",
    4: "You must define at least one outcome before continuing.",
    5: "You must define at least one task before continuing.",
    6: "How often will you check in?",
  } as Record<number, string>)[step];

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="knowledge-wizard">
      <View style={styles.headerRow}>
        <Pressable onPress={tryCancel} testID="wizard-cancel" hitSlop={12}>
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>New Learning Journey</Text>
        <View style={{ width: 56 }} />
      </View>

      {/* Progress bar */}
      <View style={styles.progressWrap}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${(step / TOTAL_STEPS) * 100}%` }]} />
        </View>
        <Text style={styles.progressLabel}>Step {step} of {TOTAL_STEPS}</Text>
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.stepTitle} testID="wizard-step-title">{stepTitle}</Text>
          <Text style={styles.stepSub}>{stepSub}</Text>

          {step === 1 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Learning Journey Title</Text>
              <TextInput
                style={styles.titleInput}
                value={state.title}
                onChangeText={(v) => set("title", v)}
                placeholder="e.g. Master Rust programming"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-title-input"
                autoFocus
              />
            </View>
          )}

          {step === 2 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Why this knowledge matters</Text>
              <TextInput
                style={styles.notes}
                value={state.why}
                onChangeText={(v) => set("why", v)}
                multiline
                textAlignVertical="top"
                placeholder="Because I want to build low-latency systems for a living."
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-why-input"
                autoFocus
              />
            </View>
          )}

          {step === 3 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Target completion date (optional)</Text>
              <DateTimeField
                mode="date"
                value={state.targetDate}
                onChange={(v) => set("targetDate", v)}
                placeholder="Choose date"
                clearable
                testID="wizard-target-date-input"
              />
            </View>
          )}

          {step === 4 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Outcome title</Text>
              <TextInput
                style={styles.input}
                value={state.outcomeTitle}
                onChangeText={(v) => set("outcomeTitle", v)}
                placeholder="e.g. Complete the Rust Book"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-outcome-title-input"
                autoFocus
              />
              <Text style={styles.label}>Target value (optional)</Text>
              <TextInput
                style={styles.input}
                value={state.outcomeTarget}
                onChangeText={(v) => set("outcomeTarget", v)}
                placeholder="e.g. 20"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-outcome-target-input"
              />
              <Text style={styles.label}>Unit (optional)</Text>
              <TextInput
                style={styles.input}
                value={state.outcomeUnit}
                onChangeText={(v) => set("outcomeUnit", v)}
                placeholder="e.g. chapters"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-outcome-unit-input"
              />
              <Text style={styles.helper}>
                You must define at least one Expected Outcome before continuing.
              </Text>
            </View>
          )}

          {step === 5 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Task title</Text>
              <TextInput
                style={styles.input}
                value={state.taskTitle}
                onChangeText={(v) => set("taskTitle", v)}
                placeholder="e.g. Read Chapter 1 & set up cargo"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="wizard-task-title-input"
                autoFocus
              />
              <Text style={styles.label}>Due date (optional)</Text>
              <DateTimeField
                mode="date"
                value={state.taskDueDate}
                onChange={(v) => set("taskDueDate", v)}
                placeholder="Choose due date"
                clearable
                testID="wizard-task-due-input"
              />
              <Text style={styles.helper}>
                You must define at least one Task before continuing.
              </Text>
            </View>
          )}

          {step === 6 && (
            <View style={styles.stepBody}>
              {CADENCE_META.map((c) => {
                const sel = state.cadence === c.key;
                return (
                  <Pressable
                    key={c.key}
                    onPress={() => set("cadence", c.key)}
                    style={[styles.cadenceRow, sel && styles.cadenceRowSelected]}
                    testID={`wizard-cadence-${c.key}`}
                  >
                    <Ionicons
                      name={c.icon}
                      size={22}
                      color={sel ? colors.onBrandPrimary : colors.brandPrimary}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.cadenceLabel, sel && styles.cadenceLabelSelected]}>{c.label}</Text>
                      <Text style={[styles.cadenceBlurb, sel && styles.cadenceBlurbSelected]}>{c.blurb}</Text>
                    </View>
                    {sel && (
                      <Ionicons name="checkmark-circle" size={22} color={colors.onBrandPrimary} />
                    )}
                  </Pressable>
                );
              })}
              <Text style={styles.helper}>
                Cadence is saved to guide you. No reminders or recurring tasks are created.
              </Text>
            </View>
          )}

          {error ? <Text style={styles.errorText} testID="wizard-error">{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          <View style={styles.footerRow}>
            <Pressable
              onPress={goPrev}
              disabled={step === 1 || busy}
              style={[styles.secondaryBtn, (step === 1 || busy) && styles.disabledOpacity]}
              testID="wizard-prev-button"
            >
              <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
              <Text style={styles.secondaryText}>Back</Text>
            </Pressable>
            {step < TOTAL_STEPS ? (
              <Pressable
                onPress={goNext}
                disabled={!canNext}
                style={[styles.primaryBtn, !canNext && styles.disabledOpacity]}
                testID="wizard-next-button"
              >
                <Text style={styles.primaryText}>Continue</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceInverse} />
              </Pressable>
            ) : (
              <Pressable
                onPress={submit}
                disabled={!canNext || busy}
                style={[styles.primaryBtn, (!canNext || busy) && styles.disabledOpacity]}
                testID="wizard-finish-button"
              >
                {busy ? (
                  <ActivityIndicator color={colors.onSurfaceInverse} />
                ) : (
                  <>
                    <Text style={styles.primaryText}>Start journey</Text>
                    <Ionicons name="checkmark" size={18} color={colors.onSurfaceInverse} />
                  </>
                )}
              </Pressable>
            )}
          </View>
        </View>
      </KeyboardAvoidingView>

      <ConfirmModal
        visible={cancelOpen}
        title="Discard this journey?"
        message="Your progress so far will be lost. Nothing has been saved yet."
        confirmLabel="Discard"
        danger
        onCancel={() => setCancelOpen(false)}
        onConfirm={() => { setCancelOpen(false); router.back(); }}
        testID="wizard-cancel-confirm"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  progressWrap: { paddingHorizontal: spacing.xl, marginBottom: spacing.md },
  progressTrack: { height: 4, backgroundColor: colors.surfaceTertiary, borderRadius: 2, overflow: "hidden" },
  progressFill: { height: 4, backgroundColor: colors.brandPrimary },
  progressLabel: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1, marginTop: spacing.xs },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xl },
  stepTitle: { fontFamily: fonts.displayBold, fontSize: 24, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 30 },
  stepSub: { fontSize: 14, color: colors.onSurfaceSecondary, marginTop: spacing.xs, lineHeight: 20 },
  stepBody: { marginTop: spacing.lg, gap: 0 },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  titleInput: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 140 },
  helper: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: spacing.lg, lineHeight: 18 },
  cadenceRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.sm,
    borderWidth: 1, borderColor: "transparent",
  },
  cadenceRowSelected: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  cadenceLabel: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  cadenceLabelSelected: { color: colors.onBrandPrimary },
  cadenceBlurb: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  cadenceBlurbSelected: { color: colors.onBrandPrimary, opacity: 0.85 },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  footerRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md, borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
  },
  secondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "500" },
  primaryBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    paddingVertical: spacing.md + 2, borderRadius: radius.pill,
    backgroundColor: colors.onSurface,
  },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "600" },
  disabledOpacity: { opacity: 0.4 },
});
