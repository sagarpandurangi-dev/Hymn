import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, EO_STATUSES, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";

type Props = {
  initial?: any;
  headerTitle: string;
  submitLabel: string;
  testIDPrefix: string;
  onSubmit: (payload: any) => Promise<void>;
  goalId: string;
};

function EOForm({ initial, headerTitle, submitLabel, testIDPrefix, onSubmit }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState(initial?.title || "");
  const [targetValue, setTargetValue] = useState(initial?.target_value || "");
  const [currentValue, setCurrentValue] = useState(initial?.current_value || "");
  const [unit, setUnit] = useState(initial?.unit || "");
  const [deadline, setDeadline] = useState(initial?.deadline || "");
  const [status, setStatus] = useState(initial?.status || "active");
  const [notes, setNotes] = useState(initial?.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    setBusy(true);
    try {
      await onSubmit({
        title: title.trim(), target_value: targetValue.trim(), current_value: currentValue.trim(),
        unit: unit.trim(), deadline: deadline.trim(), status, notes: notes.trim(),
      });
    } catch (e: any) { setError(e?.message || "Could not save"); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top", "bottom"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} testID={`${testIDPrefix}-cancel`} hitSlop={12}><Text style={s.cancel}>Cancel</Text></Pressable>
        <Text style={s.headerTitle}>{headerTitle}</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={s.label}>Title</Text>
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="What outcome are you tracking?" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-title-input`} />

          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Current</Text>
              <TextInput style={s.input} value={currentValue} onChangeText={setCurrentValue} placeholder="0" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-current-input`} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Target</Text>
              <TextInput style={s.input} value={targetValue} onChangeText={setTargetValue} placeholder="10" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-target-input`} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Unit</Text>
              <TextInput style={s.input} value={unit} onChangeText={setUnit} placeholder="books" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-unit-input`} />
            </View>
          </View>

          <Text style={s.label}>Deadline</Text>
          <TextInput style={s.input} value={deadline} onChangeText={setDeadline} placeholder="YYYY-MM-DD (optional)" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-deadline-input`} />

          <Text style={s.label}>Status</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {EO_STATUSES.map((st) => {
              const sel = status === st;
              return (
                <Pressable key={st} onPress={() => setStatus(st)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-status-chip-${st}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected, { textTransform: "capitalize" }]}>{st}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID={`${testIDPrefix}-notes-input`} />

          {error ? <Text style={s.errorText} testID={`${testIDPrefix}-error`}>{error}</Text> : null}
        </ScrollView>
        <View style={s.footer}>
          <Pressable style={[s.cta, busy && s.ctaDisabled]} onPress={save} disabled={busy} testID={`${testIDPrefix}-save-button`}>
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>{submitLabel}</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export default function AddExpectedOutcomeScreen() {
  const router = useRouter();
  const { goalId } = useLocalSearchParams<{ goalId: string }>();
  if (!goalId) return null;
  return (
    <EOForm
      goalId={goalId}
      headerTitle="Expected Outcome"
      submitLabel="Add outcome"
      testIDPrefix="add-eo"
      onSubmit={async (payload) => {
        await api.createExpectedOutcome({ goal_id: goalId, ...payload });
        router.back();
      }}
    />
  );
}

export { EOForm };
