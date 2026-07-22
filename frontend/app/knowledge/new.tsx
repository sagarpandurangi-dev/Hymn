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
import { usePostCreationDecomposition } from "@/src/lib/usePostCreationDecomposition";

type JourneyType = "professional_qualification" | "skill" | "course" | "subject" | "book" | "custom";

const JOURNEY_TYPES: { key: JourneyType; label: string; icon: keyof typeof Ionicons.glyphMap; example: string }[] = [
  { key: "professional_qualification", label: "Attain a professional qualification", icon: "ribbon-outline", example: "e.g. CA, CFA, PMP" },
  { key: "skill", label: "Learn a skill", icon: "hand-left-outline", example: "e.g. Swimming, Photography" },
  { key: "course", label: "Complete a course", icon: "school-outline", example: "e.g. Andrew Ng's ML" },
  { key: "subject", label: "Learn a subject", icon: "library-outline", example: "e.g. Python, Excel" },
  { key: "book", label: "Read a book", icon: "book-outline", example: "e.g. Bhagavad Gita" },
  { key: "custom", label: "Build a custom journey", icon: "options-outline", example: "Shape it your way" },
];

const CADENCE_META: { key: CheckinCadence; label: string; blurb: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "daily", label: "Daily", blurb: "Check in every day.", icon: "sunny-outline" },
  { key: "weekly", label: "Weekly", blurb: "Check in every week.", icon: "calendar-outline" },
  { key: "monthly", label: "Monthly", blurb: "Check in every month.", icon: "calendar-number-outline" },
  { key: "manual", label: "Manual", blurb: "Check in when you want.", icon: "hand-left-outline" },
];

type WizardState = {
  journeyType: JourneyType | "";
  title: string;
  hasStages: boolean | null;
  stages: string[]; // free-text stage names, in order
  stageInput: string;
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
  journeyType: "",
  title: "",
  hasStages: null,
  stages: [],
  stageInput: "",
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
    case 1: return !!s.journeyType;
    case 2: return s.title.trim().length > 0;
    case 3: return s.hasStages !== null;
    case 4: return s.stages.length > 0; // only reached when hasStages=true
    case 5: return s.why.trim().length > 0;
    case 6: return true;
    case 7: return s.outcomeTitle.trim().length > 0;
    case 8: return s.taskTitle.trim().length > 0;
    case 9: return !!s.cadence;
    default: return false;
  }
}

export default function KnowledgeWizardScreen() {
  const router = useRouter();
  const { handleCreatedPlannableObject, element: postCreationModal } = usePostCreationDecomposition();
  const [step, setStep] = useState(1);
  const [state, setState] = useState<WizardState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);

  const set = <K extends keyof WizardState>(k: K, v: WizardState[K]) => setState((p) => ({ ...p, [k]: v }));

  const totalSteps = state.hasStages ? 9 : 8;
  const visibleStep = state.hasStages || step < 4 ? step : step > 4 ? step - 1 : step;

  const canNext = isStepValid(step, state);

  const goNext = () => {
    setError(null);
    if (!canNext) return;
    let next = step + 1;
    if (next === 4 && !state.hasStages) next = 5; // skip stages list
    if (next > 9) return;
    setStep(next);
  };
  const goPrev = () => {
    setError(null);
    let prev = step - 1;
    if (prev === 4 && !state.hasStages) prev = 3;
    if (prev < 1) return;
    setStep(prev);
  };

  const tryCancel = () => {
    const dirty = !!state.journeyType || !!state.title.trim() || state.stages.length > 0 || !!state.why.trim() || !!state.outcomeTitle.trim() || !!state.taskTitle.trim() || !!state.cadence;
    if (dirty) setCancelOpen(true);
    else router.back();
  };

  const addStage = () => {
    const name = state.stageInput.trim();
    if (!name) return;
    setState((p) => ({ ...p, stages: [...p.stages, name], stageInput: "" }));
  };
  const removeStage = (idx: number) => {
    setState((p) => ({ ...p, stages: p.stages.filter((_, i) => i !== idx) }));
  };
  const moveStage = (idx: number, dir: -1 | 1) => {
    const next = idx + dir;
    if (next < 0 || next >= state.stages.length) return;
    const arr = [...state.stages];
    [arr[idx], arr[next]] = [arr[next], arr[idx]];
    setState((p) => ({ ...p, stages: arr }));
  };

  const submit = async () => {
    setError(null);
    if (!state.journeyType || !state.cadence || state.hasStages === null) return;
    setBusy(true);
    try {
      const created = await api.createLearningJourney({
        journey_type: state.journeyType,
        title: state.title.trim(),
        has_stages: state.hasStages,
        stages: state.hasStages ? state.stages.map((name) => ({ name })) : [],
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
      await handleCreatedPlannableObject({
        targetType: "journey",
        targetId: created.id,
        objectLabel: "Learning Journey",
        detailRoute: `/knowledge/${created.id}`,
      });
    } catch (e: any) {
      setError(e?.message || "Could not create journey. Please retry.");
    } finally {
      setBusy(false);
    }
  };

  const stepTitle = ({
    1: "I want to…",
    2: "What shall we call this journey?",
    3: "Does this journey have stages or levels?",
    4: "Add your stages",
    5: "Why does this matter?",
    6: "By when?",
    7: "First expected outcome",
    8: "First task",
    9: "Check-in cadence",
  } as Record<number, string>)[step];

  const stepSub = ({
    1: "Pick one — this shapes how your journey feels.",
    2: `Examples: ${state.journeyType === "book" ? "Bhagavad Gita" : state.journeyType === "skill" ? "Swimming, Photography" : state.journeyType === "professional_qualification" ? "CA, CFA" : state.journeyType === "subject" ? "Python, Excel" : "your call"}.`,
    3: "You'll be able to add or edit stages later.",
    4: "Name each stage in your own words. Level 1, Foundation, Beginner — anything.",
    5: "A single reason keeps you honest.",
    6: "Optional. Choose a target completion date.",
    7: "You must define at least one outcome before continuing.",
    8: "You must define at least one task before continuing.",
    9: "How often will you check in?",
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

      <View style={styles.progressWrap}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${(visibleStep / totalSteps) * 100}%` }]} />
        </View>
        <Text style={styles.progressLabel}>Step {visibleStep} of {totalSteps}</Text>
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.stepTitle} testID="wizard-step-title">{stepTitle}</Text>
          <Text style={styles.stepSub}>{stepSub}</Text>

          {step === 1 && (
            <View style={styles.stepBody}>
              {JOURNEY_TYPES.map((t) => {
                const sel = state.journeyType === t.key;
                return (
                  <Pressable
                    key={t.key}
                    onPress={() => set("journeyType", t.key)}
                    style={[styles.typeRow, sel && styles.typeRowSelected]}
                    testID={`wizard-type-${t.key}`}
                  >
                    <Ionicons name={t.icon} size={22} color={sel ? colors.onBrandPrimary : colors.brandPrimary} />
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.typeLabel, sel && styles.typeLabelSelected]}>{t.label}</Text>
                      <Text style={[styles.typeExample, sel && styles.typeExampleSelected]}>{t.example}</Text>
                    </View>
                    {sel && <Ionicons name="checkmark-circle" size={22} color={colors.onBrandPrimary} />}
                  </Pressable>
                );
              })}
            </View>
          )}

          {step === 2 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Journey name</Text>
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

          {step === 3 && (
            <View style={styles.stepBody}>
              <Pressable
                onPress={() => set("hasStages", true)}
                style={[styles.typeRow, state.hasStages === true && styles.typeRowSelected]}
                testID="wizard-has-stages-yes"
              >
                <Ionicons name="layers-outline" size={22} color={state.hasStages === true ? colors.onBrandPrimary : colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.typeLabel, state.hasStages === true && styles.typeLabelSelected]}>Yes, it has stages or levels</Text>
                  <Text style={[styles.typeExample, state.hasStages === true && styles.typeExampleSelected]}>Level 1, Foundation, Beginner…</Text>
                </View>
                {state.hasStages === true && <Ionicons name="checkmark-circle" size={22} color={colors.onBrandPrimary} />}
              </Pressable>
              <Pressable
                onPress={() => set("hasStages", false)}
                style={[styles.typeRow, state.hasStages === false && styles.typeRowSelected]}
                testID="wizard-has-stages-no"
              >
                <Ionicons name="remove-outline" size={22} color={state.hasStages === false ? colors.onBrandPrimary : colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.typeLabel, state.hasStages === false && styles.typeLabelSelected]}>No, keep it flat</Text>
                  <Text style={[styles.typeExample, state.hasStages === false && styles.typeExampleSelected]}>Components sit directly under the journey.</Text>
                </View>
                {state.hasStages === false && <Ionicons name="checkmark-circle" size={22} color={colors.onBrandPrimary} />}
              </Pressable>
            </View>
          )}

          {step === 4 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Stages ({state.stages.length})</Text>
              {state.stages.map((s, i) => (
                <View key={`${s}-${i}`} style={styles.stageRow} testID={`wizard-stage-row-${i}`}>
                  <Text style={styles.stageIndex}>{i + 1}.</Text>
                  <Text style={styles.stageName} numberOfLines={1}>{s}</Text>
                  <Pressable onPress={() => moveStage(i, -1)} hitSlop={8} disabled={i === 0} style={i === 0 ? styles.disabled : undefined} testID={`wizard-stage-up-${i}`}>
                    <Ionicons name="arrow-up" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                  <Pressable onPress={() => moveStage(i, 1)} hitSlop={8} disabled={i === state.stages.length - 1} style={i === state.stages.length - 1 ? styles.disabled : undefined} testID={`wizard-stage-down-${i}`}>
                    <Ionicons name="arrow-down" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                  <Pressable onPress={() => removeStage(i)} hitSlop={8} testID={`wizard-stage-remove-${i}`}>
                    <Ionicons name="close" size={18} color={colors.error} />
                  </Pressable>
                </View>
              ))}
              <View style={styles.stageAddRow}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  value={state.stageInput}
                  onChangeText={(v) => set("stageInput", v)}
                  placeholder="Stage name (e.g. Foundation)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  onSubmitEditing={addStage}
                  returnKeyType="done"
                  testID="wizard-stage-input"
                />
                <Pressable
                  onPress={addStage}
                  disabled={!state.stageInput.trim()}
                  style={[styles.addStageBtn, !state.stageInput.trim() && styles.disabled]}
                  testID="wizard-stage-add"
                >
                  <Ionicons name="add" size={22} color={colors.onSurfaceInverse} />
                </Pressable>
              </View>
              <Text style={styles.helper}>You need at least one stage to continue. Names are yours to choose.</Text>
            </View>
          )}

          {step === 5 && (
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

          {step === 6 && (
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

          {step === 7 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Outcome title</Text>
              <TextInput style={styles.input} value={state.outcomeTitle} onChangeText={(v) => set("outcomeTitle", v)} placeholder="e.g. Complete the Rust Book" placeholderTextColor={colors.onSurfaceTertiary} testID="wizard-outcome-title-input" autoFocus />
              <Text style={styles.label}>Target value (optional)</Text>
              <TextInput style={styles.input} value={state.outcomeTarget} onChangeText={(v) => set("outcomeTarget", v)} placeholder="e.g. 20" placeholderTextColor={colors.onSurfaceTertiary} testID="wizard-outcome-target-input" />
              <Text style={styles.label}>Unit (optional)</Text>
              <TextInput style={styles.input} value={state.outcomeUnit} onChangeText={(v) => set("outcomeUnit", v)} placeholder="e.g. chapters" placeholderTextColor={colors.onSurfaceTertiary} testID="wizard-outcome-unit-input" />
            </View>
          )}

          {step === 8 && (
            <View style={styles.stepBody}>
              <Text style={styles.label}>Task title</Text>
              <TextInput style={styles.input} value={state.taskTitle} onChangeText={(v) => set("taskTitle", v)} placeholder="e.g. Read Chapter 1" placeholderTextColor={colors.onSurfaceTertiary} testID="wizard-task-title-input" autoFocus />
              <Text style={styles.label}>Due date (optional)</Text>
              <DateTimeField mode="date" value={state.taskDueDate} onChange={(v) => set("taskDueDate", v)} placeholder="Choose due date" clearable testID="wizard-task-due-input" />
            </View>
          )}

          {step === 9 && (
            <View style={styles.stepBody}>
              {CADENCE_META.map((c) => {
                const sel = state.cadence === c.key;
                return (
                  <Pressable key={c.key} onPress={() => set("cadence", c.key)} style={[styles.typeRow, sel && styles.typeRowSelected]} testID={`wizard-cadence-${c.key}`}>
                    <Ionicons name={c.icon} size={22} color={sel ? colors.onBrandPrimary : colors.brandPrimary} />
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.typeLabel, sel && styles.typeLabelSelected]}>{c.label}</Text>
                      <Text style={[styles.typeExample, sel && styles.typeExampleSelected]}>{c.blurb}</Text>
                    </View>
                    {sel && <Ionicons name="checkmark-circle" size={22} color={colors.onBrandPrimary} />}
                  </Pressable>
                );
              })}
              <Text style={styles.helper}>Cadence is saved to guide you. No reminders or recurring tasks are created.</Text>
            </View>
          )}

          {error ? <Text style={styles.errorText} testID="wizard-error">{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          <View style={styles.footerRow}>
            <Pressable onPress={goPrev} disabled={step === 1 || busy} style={[styles.secondaryBtn, (step === 1 || busy) && styles.disabled]} testID="wizard-prev-button">
              <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
              <Text style={styles.secondaryText}>Back</Text>
            </Pressable>
            {step < 9 ? (
              <Pressable onPress={goNext} disabled={!canNext} style={[styles.primaryBtn, !canNext && styles.disabled]} testID="wizard-next-button">
                <Text style={styles.primaryText}>Continue</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceInverse} />
              </Pressable>
            ) : (
              <Pressable onPress={submit} disabled={!canNext || busy} style={[styles.primaryBtn, (!canNext || busy) && styles.disabled]} testID="wizard-finish-button">
                {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : (
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
      {postCreationModal}
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
  stepBody: { marginTop: spacing.lg },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  titleInput: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 140 },
  helper: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: spacing.lg, lineHeight: 18 },
  typeRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.sm,
    borderWidth: 1, borderColor: "transparent",
  },
  typeRowSelected: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  typeLabel: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  typeLabelSelected: { color: colors.onBrandPrimary },
  typeExample: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  typeExampleSelected: { color: colors.onBrandPrimary, opacity: 0.85 },
  stageRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, marginTop: spacing.sm,
  },
  stageIndex: { fontSize: 12, color: colors.onSurfaceTertiary, width: 20 },
  stageName: { flex: 1, fontSize: 15, color: colors.onSurface },
  stageAddRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md },
  addStageBtn: {
    width: 46, height: 46, borderRadius: radius.sm,
    backgroundColor: colors.onSurface,
    alignItems: "center", justifyContent: "center",
  },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  footerRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  secondaryBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary },
  secondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "500" },
  primaryBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: spacing.md + 2, borderRadius: radius.pill, backgroundColor: colors.onSurface },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "600" },
  disabled: { opacity: 0.35 },
});
