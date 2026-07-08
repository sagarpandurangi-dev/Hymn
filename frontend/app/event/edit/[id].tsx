import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing, EVENT_TYPES } from "@/src/lib/theme";

export default function EditEventScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [type, setType] = useState<string>(EVENT_TYPES[0]);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const e = await api.getEvent(id);
      setType(e.type); setTitle(e.title); setDate(e.date); setTime(e.time); setNotes(e.notes || "");
    } catch (e: any) {
      setError(e?.message || "Could not load event");
    } finally { setLoading(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const onSave = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { setError("Date must be YYYY-MM-DD."); return; }
    if (!/^\d{2}:\d{2}$/.test(time)) { setError("Time must be HH:MM."); return; }
    setBusy(true);
    try {
      await api.updateEvent(id!, { type, title: title.trim(), date, time, notes: notes.trim() });
      router.back();
    } catch (e: any) {
      setError(e?.message || "Could not save");
    } finally { setBusy(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="edit-event-cancel" hitSlop={12}>
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>Edit Event</Text>
        <View style={{ width: 56 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.flex}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Type</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {EVENT_TYPES.map((t) => {
              const selected = type === t;
              return (
                <Pressable key={t} onPress={() => setType(t)} style={[styles.chip, selected && styles.chipSelected]} testID={`edit-type-chip-${t}`}>
                  <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{t}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={styles.label}>Title</Text>
          <TextInput style={styles.titleInput} value={title} onChangeText={setTitle} testID="edit-event-title-input" />

          <View style={styles.dateTimeRow}>
            <View style={styles.dateTimeCol}>
              <Text style={styles.label}>Date</Text>
              <TextInput style={styles.input} value={date} onChangeText={setDate} testID="edit-event-date-input" />
            </View>
            <View style={styles.dateTimeCol}>
              <Text style={styles.label}>Time</Text>
              <TextInput style={styles.input} value={time} onChangeText={setTime} testID="edit-event-time-input" />
            </View>
          </View>

          <Text style={styles.label}>Notes</Text>
          <TextInput
            style={styles.notes}
            value={notes}
            onChangeText={setNotes}
            multiline
            textAlignVertical="top"
            testID="edit-event-notes-input"
          />

          {error ? <Text style={styles.errorText} testID="edit-event-error">{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={onSave} disabled={busy} testID="edit-event-save-button">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.ctaText}>Save changes</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  chipRow: { gap: spacing.sm, paddingRight: spacing.xl },
  chip: {
    flexShrink: 0, height: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center",
  },
  chipSelected: { backgroundColor: colors.brandPrimary },
  chipText: { color: colors.onBrandTertiary, fontSize: 13, fontWeight: "500" },
  chipTextSelected: { color: colors.onBrandPrimary },
  titleInput: { fontFamily: fonts.displayBold, fontSize: 24, color: colors.onSurface, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  dateTimeRow: { flexDirection: "row", gap: spacing.md },
  dateTimeCol: { flex: 1 },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 140 },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
