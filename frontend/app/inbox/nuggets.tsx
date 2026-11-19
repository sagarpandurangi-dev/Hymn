import { useCallback, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { api, ApiError, InboxItem } from "@/src/lib/api";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import InboxItemRow from "@/src/components/InboxItemRow";

type Destination = "task" | "calendar" | "wishlist";
type Project = { id: string; title: string };

const DESTINATIONS: { value: Destination; label: string }[] = [
  { value: "task", label: "Task" },
  { value: "calendar", label: "Calendar" },
  { value: "wishlist", label: "Wishlist" },
];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}$/;

function NuggetCard({
  nugget,
  projects,
  onMigrated,
}: {
  nugget: InboxItem;
  projects: Project[];
  onMigrated: (id: string) => void;
}) {
  const [destination, setDestination] = useState<Destination | null>(null);
  const [nextStep, setNextStep] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [time, setTime] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const move = async () => {
    if (!destination || saving) return;
    const step = nextStep.trim();
    if (!step) { setError("The next step is required."); return; }
    const payload: Parameters<typeof api.migrateInboxItem>[1] = { destination, next_step: step };
    if (destination === "calendar") {
      if (!DATE_RE.test(dueDate.trim())) { setError("Enter a date as YYYY-MM-DD."); return; }
      payload.due_date = dueDate.trim();
      if (time.trim()) {
        if (!TIME_RE.test(time.trim())) { setError("Enter the time as HH:MM."); return; }
        payload.time = time.trim();
      }
    }
    if (destination === "task" && projectId) payload.project_id = projectId;
    setSaving(true);
    setError("");
    try {
      await api.migrateInboxItem(nugget.id, payload);
      onMigrated(nugget.id);
    } catch (e) {
      setError((e as ApiError).message);
      setSaving(false);
    }
  };

  return (
    <InboxItemRow text={nugget.text} category={nugget.category} testID={`nugget-${nugget.id}`}>
      <Text style={styles.question}>Where should this live?</Text>
      <View style={styles.chipWrap}>
        {DESTINATIONS.map((d) => {
          const sel = destination === d.value;
          return (
            <Pressable
              key={d.value}
              onPress={() => { setDestination(d.value); setError(""); }}
              style={[s.chip, sel && s.chipSelected]}
              testID={`nugget-dest-${d.value}-${nugget.id}`}
            >
              <Text style={[s.chipText, sel && s.chipTextSelected]}>{d.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {destination ? (
        <>
          <Text style={styles.question}>What’s the very next step?</Text>
          <TextInput
            style={[s.input, styles.input]}
            value={nextStep}
            onChangeText={setNextStep}
            placeholder="e.g. Email Sam to ask for the quote"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID={`nugget-next-step-${nugget.id}`}
          />

          {destination === "calendar" ? (
            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.fieldLabel}>Date</Text>
                <TextInput
                  style={[s.input, styles.input]}
                  value={dueDate}
                  onChangeText={setDueDate}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  testID={`nugget-date-${nugget.id}`}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.fieldLabel}>Time (optional)</Text>
                <TextInput
                  style={[s.input, styles.input]}
                  value={time}
                  onChangeText={setTime}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  testID={`nugget-time-${nugget.id}`}
                />
              </View>
            </View>
          ) : null}

          {destination === "task" && projects.length > 0 ? (
            <>
              <Text style={styles.fieldLabel}>Project (optional)</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                {projects.map((p) => {
                  const sel = projectId === p.id;
                  return (
                    <Pressable
                      key={p.id}
                      onPress={() => setProjectId(sel ? null : p.id)}
                      style={[s.chip, sel && s.chipSelected]}
                      testID={`nugget-project-${p.id}-${nugget.id}`}
                    >
                      <Text style={[s.chipText, sel && s.chipTextSelected]} numberOfLines={1}>{p.title}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </>
          ) : null}

          {error ? <Text style={s.errorText} testID={`nugget-error-${nugget.id}`}>{error}</Text> : null}
          <Pressable
            style={[s.cta, saving && s.ctaDisabled]}
            onPress={move}
            disabled={saving}
            testID={`nugget-move-${nugget.id}`}
          >
            {saving ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Move</Text>}
          </Pressable>
        </>
      ) : null}
    </InboxItemRow>
  );
}

export default function NuggetsScreen() {
  const router = useRouter();
  const [nuggets, setNuggets] = useState<InboxItem[]>([]);
  const [prompt, setPrompt] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [review, projectList] = await Promise.all([
        api.getInboxReview(),
        api.listProjects().catch(() => []),
      ]);
      setNuggets(review.nuggets || []);
      setPrompt(review.migrate_prompt || "");
      setProjects(projectList as Project[]);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        setLoading(true);
        await load();
        if (alive) setLoading(false);
      })();
      return () => { alive = false; };
    }, [load]),
  );

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="nuggets-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Nuggets</Text>
        <View style={{ width: 56 }} />
      </View>
      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
          <ScrollView contentContainerStyle={[s.scroll, { gap: spacing.sm }]} keyboardShouldPersistTaps="handled">
            {prompt ? <Text style={styles.prompt}>{prompt}</Text> : null}
            {error ? <Text style={s.errorText} testID="nuggets-error">{error}</Text> : null}
            {nuggets.length === 0 && !error ? (
              <Text style={styles.empty} testID="nuggets-empty">No nuggets waiting. Mark items as Gold in your daily review.</Text>
            ) : null}
            {nuggets.map((n) => (
              <NuggetCard
                key={n.id}
                nugget={n}
                projects={projects}
                onMigrated={(id) => setNuggets((prev) => prev.filter((x) => x.id !== id))}
              />
            ))}
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  question: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  fieldLabel: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, letterSpacing: 0.5 },
  chipWrap: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  input: { backgroundColor: colors.surface },
  prompt: { fontSize: 15, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary },
});
