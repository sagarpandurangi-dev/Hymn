import { useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing, EVENT_TYPES } from "@/src/lib/theme";

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const nowDate = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const nowTime = () => {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export default function AddEventScreen() {
  const router = useRouter();
  const [type, setType] = useState<string>(EVENT_TYPES[0]);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(nowDate());
  const [time, setTime] = useState(nowTime());
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSave = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { setError("Date must be YYYY-MM-DD."); return; }
    if (!/^\d{2}:\d{2}$/.test(time)) { setError("Time must be HH:MM."); return; }
    setBusy(true);
    try {
      await api.createEvent({ type, title: title.trim(), date, time, notes: notes.trim() });
      router.back();
    } catch (e: any) {
      setError(e?.message || "Could not save event");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="add-event-cancel" hitSlop={12}>
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>New Event</Text>
        <View style={{ width: 56 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.flex}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Type</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {EVENT_TYPES.map((t) => {
              const selected = type === t;
              return (
                <Pressable
                  key={t}
                  onPress={() => setType(t)}
                  style={[styles.chip, selected && styles.chipSelected]}
                  testID={`type-chip-${t}`}
                >
                  <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{t}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={styles.label}>Title</Text>
          <TextInput
            style={styles.titleInput}
            value={title}
            onChangeText={setTitle}
            placeholder="A phrase you'll remember"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="add-event-title-input"
          />

          <View style={styles.dateTimeRow}>
            <View style={styles.dateTimeCol}>
              <Text style={styles.label}>Date</Text>
              <TextInput
                style={styles.input}
                value={date}
                onChangeText={setDate}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="add-event-date-input"
              />
            </View>
            <View style={styles.dateTimeCol}>
              <Text style={styles.label}>Time</Text>
              <TextInput
                style={styles.input}
                value={time}
                onChangeText={setTime}
                placeholder="HH:MM"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="add-event-time-input"
              />
            </View>
          </View>

          <Text style={styles.label}>Notes</Text>
          <TextInput
            style={styles.notes}
            value={notes}
            onChangeText={setNotes}
            placeholder="What actually happened?"
            placeholderTextColor={colors.onSurfaceTertiary}
            multiline
            textAlignVertical="top"
            testID="add-event-notes-input"
          />

          {error ? <Text style={styles.errorText} testID="add-event-error">{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={onSave} disabled={busy} testID="add-event-save-button">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : (
              <View style={styles.ctaContent}>
                <Ionicons name="checkmark" size={18} color={colors.onSurfaceInverse} />
                <Text style={styles.ctaText}>Save event</Text>
              </View>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
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
  titleInput: {
    fontFamily: fonts.displayBold, fontSize: 24, color: colors.onSurface,
    paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  dateTimeRow: { flexDirection: "row", gap: spacing.md },
  dateTimeCol: { flex: 1 },
  input: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface,
  },
  notes: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 140,
  },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaContent: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
