import { useRef, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api, ApiError, InboxDumpResponse } from "@/src/lib/api";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import InboxItemRow from "@/src/components/InboxItemRow";

const newDumpId = () =>
  `dump-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;

export default function BrainDumpScreen() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [sorting, setSorting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InboxDumpResponse | null>(null);
  // One id per submit; a retry of the same text reuses it.
  const pendingRef = useRef<{ text: string; id: string } | null>(null);

  const save = async () => {
    const body = text.trim();
    if (!body || saving) return;
    if (!pendingRef.current || pendingRef.current.text !== body) {
      pendingRef.current = { text: body, id: newDumpId() };
    }
    setSaving(true);
    setError("");
    try {
      const res = await api.createInboxDump({
        text: body,
        client_dump_id: pendingRef.current.id,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      pendingRef.current = null;
      setResult(res);
      setText("");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  const sortAgain = async () => {
    if (!result || sorting) return;
    setSorting(true);
    setError("");
    try {
      setResult(await api.sortInboxDump(result.dump.id));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSorting(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="dump-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Brain dump</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <TextInput
            style={[s.notes, { minHeight: 220, textAlignVertical: "top" }]}
            value={text}
            onChangeText={setText}
            multiline
            placeholder="Everything on your mind — tasks, reminders, ideas, plans…"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="dump-text-input"
          />
          {error ? <Text style={s.errorText} testID="dump-error">{error}</Text> : null}
          <Pressable
            style={[s.cta, { marginTop: spacing.lg }, (!text.trim() || saving) && s.ctaDisabled]}
            onPress={save}
            disabled={!text.trim() || saving}
            testID="dump-save-button"
          >
            {saving ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save</Text>}
          </Pressable>

          {result ? (
            <View style={{ marginTop: spacing.xl, gap: spacing.sm }}>
              <Text style={[s.rowTitle, { marginBottom: spacing.xs }]} testID="dump-ack">{result.ack}</Text>
              {result.items.map((it) => (
                <InboxItemRow key={it.id} text={it.text} category={it.category} testID={`dump-item-${it.id}`} />
              ))}
              {result.dump.status === "unsorted" ? (
                <Pressable
                  style={[s.chip, { alignSelf: "flex-start", marginTop: spacing.sm }, sorting && s.ctaDisabled]}
                  onPress={sortAgain}
                  disabled={sorting}
                  testID="dump-sort-again-button"
                >
                  {sorting ? <ActivityIndicator color={colors.onBrandTertiary} /> : <Text style={s.chipText}>Sort again</Text>}
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
