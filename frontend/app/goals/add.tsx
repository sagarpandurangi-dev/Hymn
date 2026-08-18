import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing, GOAL_STATUSES } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";
import { usePostCreationDecomposition } from "@/src/lib/usePostCreationDecomposition";
import CommitmentTypeToggle from "@/src/components/CommitmentTypeToggle";

type Domain = { id: string; name: string };

type Props = {
  mode: "add" | "edit";
  initial?: {
    title: string; domain_id: string; target_outcome: string; deadline: string; status: string; notes: string;
    commitment_type?: "postponable" | "exclusive";
    checkin_cadence?: string;
    checkin_anchor_date?: string;
  } | null;
  onSubmit: (payload: { title: string; domain_id: string; target_outcome: string; deadline: string; status: string; notes: string; commitment_type: "postponable" | "exclusive"; checkin_cadence: string; checkin_anchor_date: string }) => Promise<void>;
  headerTitle: string;
  submitLabel: string;
  testIDPrefix: string;
};

// Cadence catalogue rendered as chips. Kept aligned with
// `backend/recurrence.py::EXTENDED_CHECKIN_CADENCES` — see also
// `/app/frontend/src/components/RecurrenceSheet.tsx` for the label mapping
// used by task recurrence (identical vocabulary).
const CADENCE_OPTIONS: { value: string; label: string }[] = [
  { value: "",              label: "None" },
  { value: "daily",         label: "Daily" },
  { value: "alternate_day", label: "Alternate day" },
  { value: "weekly",        label: "Weekly" },
  { value: "fortnightly",   label: "Fortnightly" },
  { value: "monthly",       label: "Monthly" },
  { value: "quarterly",     label: "Quarterly" },
  { value: "half_yearly",   label: "Half-yearly" },
  { value: "yearly",        label: "Yearly" },
  { value: "manual",        label: "Manual" },
];

export function GoalForm({ initial, onSubmit, headerTitle, submitLabel, testIDPrefix }: Props) {
  const router = useRouter();
  const [domains, setDomains] = useState<Domain[]>([]);
  const [title, setTitle] = useState(initial?.title || "");
  const [domainId, setDomainId] = useState<string>(initial?.domain_id || "");
  const [target, setTarget] = useState(initial?.target_outcome || "");
  const [deadline, setDeadline] = useState(initial?.deadline || "");
  const [status, setStatus] = useState<string>(initial?.status || "active");
  const [notes, setNotes] = useState(initial?.notes || "");
  const [commitmentType, setCommitmentType] = useState<"postponable" | "exclusive">(initial?.commitment_type || "postponable");
  const [cadence, setCadence] = useState<string>(initial?.checkin_cadence || "");
  const [cadenceAnchor, setCadenceAnchor] = useState<string>(initial?.checkin_anchor_date || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await api.listDomains();
        setDomains(d.map((x) => ({ id: x.id, name: x.name })));
        if (!domainId && d.length > 0) setDomainId(d[0].id);
      } catch { /* ignore */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    if (!domainId) { setError("Choose a domain."); return; }
    if (deadline && !/^\d{4}-\d{2}-\d{2}$/.test(deadline)) { setError("Deadline must be YYYY-MM-DD or empty."); return; }
    setBusy(true);
    try {
      await onSubmit({
        title: title.trim(),
        domain_id: domainId,
        target_outcome: target.trim(),
        deadline: deadline.trim(),
        status,
        notes: notes.trim(),
        commitment_type: commitmentType,
        checkin_cadence: cadence,
        checkin_anchor_date: cadenceAnchor.trim(),
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
            placeholder="What are you working towards?"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`${testIDPrefix}-title-input`}
          />

          <Text style={styles.label}>Domain</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {domains.map((d) => {
              const sel = domainId === d.id;
              return (
                <Pressable
                  key={d.id}
                  onPress={() => setDomainId(d.id)}
                  style={[styles.chip, sel && styles.chipSelected]}
                  testID={`${testIDPrefix}-domain-chip-${d.name}`}
                >
                  <Text style={[styles.chipText, sel && styles.chipTextSelected]}>{d.name}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={styles.label}>Target Outcome</Text>
          <TextInput
            style={styles.input}
            value={target}
            onChangeText={setTarget}
            placeholder="What does success look like?"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`${testIDPrefix}-target-input`}
          />

          <Text style={styles.label}>Deadline</Text>
          <DateTimeField
            mode="date"
            value={deadline}
            onChange={setDeadline}
            placeholder="Choose date (optional)"
            clearable
            testID={`${testIDPrefix}-deadline-input`}
          />

          <Text style={styles.label}>Status</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {GOAL_STATUSES.map((s) => {
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

          <Text style={styles.label}>Commitment</Text>
          <CommitmentTypeToggle value={commitmentType} onChange={setCommitmentType} testID={`${testIDPrefix}-commitment`} />

          {/* Check-in cadence — how often the goal expects a fresh
              check-in. This drives `/api/checkins/required` and is
              inherited by any task linked to this goal.  Anchor date is
              optional; when blank the backend falls back to the goal's
              creation date. */}
          <Text style={styles.label}>Check-in cadence</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {CADENCE_OPTIONS.map((opt) => {
              const sel = cadence === opt.value;
              return (
                <Pressable
                  key={opt.value || "none"}
                  onPress={() => setCadence(opt.value)}
                  style={[styles.chip, sel && styles.chipSelected]}
                  testID={`${testIDPrefix}-cadence-${opt.value || "none"}`}
                >
                  <Text style={[styles.chipText, sel && styles.chipTextSelected]}>{opt.label}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          {cadence && cadence !== "manual" ? (
            <>
              <Text style={styles.helpText}>
                Anchor date — the cadence is computed from this day. Leave blank to use today.
              </Text>
              <DateTimeField
                mode="date"
                value={cadenceAnchor}
                onChange={setCadenceAnchor}
                placeholder="Choose date (optional)"
                clearable
                testID={`${testIDPrefix}-cadence-anchor`}
              />
            </>
          ) : null}

          <Text style={styles.label}>Notes</Text>
          <TextInput
            style={styles.notes}
            value={notes}
            onChangeText={setNotes}
            multiline
            textAlignVertical="top"
            placeholder="Anything else that matters?"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`${testIDPrefix}-notes-input`}
          />

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

export default function AddGoalScreen() {
  const { handleCreatedPlannableObject, element } = usePostCreationDecomposition();
  return (
    <>
      <GoalForm
        mode="add"
        headerTitle="New Goal"
        submitLabel="Create goal"
        testIDPrefix="add-goal"
        onSubmit={async (payload) => {
          const created = await api.createGoal(payload);
          await handleCreatedPlannableObject({
            targetType: "goal",
            targetId: created.id,
            objectLabel: "Goal",
            detailRoute: `/goals/${created.id}`,
          });
        }}
      />
      {element}
    </>
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
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 120 },
  chipRow: { gap: spacing.sm, paddingRight: spacing.xl },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  chipSelected: { backgroundColor: colors.brandPrimary },
  chipText: { color: colors.onBrandTertiary, fontSize: 13, fontWeight: "500" },
  chipTextSelected: { color: colors.onBrandPrimary },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  helpText: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: spacing.sm, marginBottom: 4, fontStyle: "italic", lineHeight: 16 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
