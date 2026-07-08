import { useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Switch, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const nowDate = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const nowTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };

export default function LifeCheckinScreen() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(nowDate());
  const [time, setTime] = useState(nowTime());
  const [notes, setNotes] = useState("");
  const [attachment, setAttachment] = useState("");
  const [addFollowUp, setAddFollowUp] = useState(false);
  const [followUpTitle, setFollowUpTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    setBusy(true);
    try {
      const payload: any = { type: "life", title: title.trim(), date, time, notes: notes.trim(), attachment, source: "manual" };
      if (addFollowUp && followUpTitle.trim()) payload.follow_up_task = { title: followUpTitle.trim() };
      await api.createCheckin(payload);
      router.back();
    } catch (e: any) { setError(e?.message || "Could not save"); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top", "bottom"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} testID="life-checkin-cancel" hitSlop={12}><Text style={s.cancel}>Cancel</Text></Pressable>
        <Text style={s.headerTitle}>Life Check-in</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={s.label}>Title</Text>
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="What are you noting?" placeholderTextColor={colors.onSurfaceTertiary} testID="life-checkin-title-input" />

          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Date</Text>
              <TextInput style={s.input} value={date} onChangeText={setDate} testID="life-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <TextInput style={s.input} value={time} onChangeText={setTime} testID="life-checkin-time-input" />
            </View>
          </View>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="life-checkin-notes-input" />

          <Text style={s.label}>Attachment (paste URL — placeholder)</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} testID="life-checkin-attachment-input" />

          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.lg }}>
            <Text style={{ fontSize: 14, color: colors.onSurface }}>Create follow-up task</Text>
            <Switch value={addFollowUp} onValueChange={setAddFollowUp} testID="life-checkin-followup-switch" />
          </View>
          {addFollowUp && (
            <TextInput style={[s.input, { marginTop: spacing.sm }]} value={followUpTitle} onChangeText={setFollowUpTitle} placeholder="Follow-up task title" placeholderTextColor={colors.onSurfaceTertiary} testID="life-checkin-followup-title-input" />
          )}

          {error ? <Text style={s.errorText} testID="life-checkin-error">{error}</Text> : null}
        </ScrollView>

        <View style={s.footer}>
          <Pressable style={[s.cta, busy && s.ctaDisabled]} onPress={onSave} disabled={busy} testID="life-checkin-save-button">
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save check-in</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
