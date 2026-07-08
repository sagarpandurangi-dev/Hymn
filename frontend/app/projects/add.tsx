import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, PROJECT_STATUSES, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";

type Props = {
  initial?: { title: string; description: string; status: string; start_date: string; target_end_date: string; notes: string } | null;
  headerTitle: string;
  submitLabel: string;
  testIDPrefix: string;
  onSubmit: (payload: { title: string; description: string; status: string; start_date: string; target_end_date: string; notes: string }) => Promise<void>;
};

export function ProjectForm({ initial, headerTitle, submitLabel, testIDPrefix, onSubmit }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState(initial?.title || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [status, setStatus] = useState(initial?.status || "active");
  const [startDate, setStartDate] = useState(initial?.start_date || "");
  const [targetEnd, setTargetEnd] = useState(initial?.target_end_date || "");
  const [notes, setNotes] = useState(initial?.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    setBusy(true);
    try {
      await onSubmit({ title: title.trim(), description: description.trim(), status, start_date: startDate.trim(), target_end_date: targetEnd.trim(), notes: notes.trim() });
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
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="Project title" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-title-input`} />

          <Text style={s.label}>Description</Text>
          <TextInput style={s.input} value={description} onChangeText={setDescription} placeholder="Short description" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-description-input`} />

          <Text style={s.label}>Status</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {PROJECT_STATUSES.map((st) => {
              const sel = status === st;
              return (
                <Pressable key={st} onPress={() => setStatus(st)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-status-chip-${st}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected, { textTransform: "capitalize" }]}>{st}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Start Date</Text>
              <TextInput style={s.input} value={startDate} onChangeText={setStartDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-start-input`} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Target End</Text>
              <TextInput style={s.input} value={targetEnd} onChangeText={setTargetEnd} placeholder="YYYY-MM-DD" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-end-input`} />
            </View>
          </View>

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

export default function AddProjectScreen() {
  const router = useRouter();
  return (
    <ProjectForm
      headerTitle="New Project"
      submitLabel="Create project"
      testIDPrefix="add-project"
      onSubmit={async (payload) => { await api.createProject(payload); router.back(); }}
    />
  );
}
