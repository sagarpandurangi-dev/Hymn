import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import DateTimeField from "@/src/components/DateTimeField";

export default function EditCheckinScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [attachment, setAttachment] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const c = await api.getCheckin(id);
        setTitle(c.title); setDate(c.date); setTime(c.time); setNotes(c.notes || ""); setAttachment(c.attachment || "");
      } catch (e: any) { setError(e?.message || "Could not load"); }
      finally { setLoading(false); }
    })();
  }, [id]);

  const onSave = async () => {
    if (!id) return;
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    setBusy(true);
    try {
      await api.updateCheckin(id, { title: title.trim(), date, time, notes: notes.trim(), attachment: attachment.trim() });
      router.back();
    } catch (e: any) { setError(e?.message || "Could not save"); }
    finally { setBusy(false); }
  };

  if (loading) return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={s.safe} edges={["top", "bottom"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} testID="edit-checkin-cancel" hitSlop={12}><Text style={s.cancel}>Cancel</Text></Pressable>
        <Text style={s.headerTitle}>Edit Check-in</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={s.label}>Title</Text>
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} testID="edit-checkin-title-input" />
          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Date</Text>
              <DateTimeField mode="date" value={date} onChange={setDate} testID="edit-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <DateTimeField mode="time" value={time} onChange={setTime} testID="edit-checkin-time-input" />
            </View>
          </View>
          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="edit-checkin-notes-input" />
          <Text style={s.label}>Attachment</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} testID="edit-checkin-attachment-input" />
          {error ? <Text style={s.errorText} testID="edit-checkin-error">{error}</Text> : null}
        </ScrollView>
        <View style={s.footer}>
          <Pressable style={[s.cta, busy && s.ctaDisabled]} onPress={onSave} disabled={busy} testID="edit-checkin-save-button">
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save changes</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
