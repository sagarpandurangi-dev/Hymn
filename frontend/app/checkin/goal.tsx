import { useEffect, useState } from "react";
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

type Goal = { id: string; title: string };
type EO = { id: string; goal_id: string; title: string; outcome_type: string };
type FieldDef = { key: string; label: string; type: string; required?: boolean; options?: string[] };

export default function GoalCheckinScreen() {
  const router = useRouter();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [eos, setEos] = useState<EO[]>([]);
  const [goalId, setGoalId] = useState<string>("");
  const [eoId, setEoId] = useState<string>("");
  const [registry, setRegistry] = useState<Record<string, { label: string; checkin_fields: FieldDef[] }>>({});
  const [dynamicData, setDynamicData] = useState<Record<string, any>>({});
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(nowDate());
  const [time, setTime] = useState(nowTime());
  const [notes, setNotes] = useState("");
  const [attachment, setAttachment] = useState("");
  const [addFollowUp, setAddFollowUp] = useState(false);
  const [followUpTitle, setFollowUpTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [gs, reg] = await Promise.all([api.listGoals(), api.getOutcomeTypes()]);
        setGoals(gs.map((g) => ({ id: g.id, title: g.title })));
        setRegistry(reg.types as any);
        if (gs.length > 0) setGoalId(gs[0].id);
      } catch { /* ignore */ }
    })();
  }, []);

  useEffect(() => {
    if (!goalId) { setEos([]); return; }
    (async () => {
      try {
        const list = await api.listExpectedOutcomes(goalId);
        setEos(list.map((x) => ({ id: x.id, goal_id: x.goal_id, title: x.title, outcome_type: (x as any).outcome_type || "generic" })));
        setEoId(list[0]?.id || "");
      } catch { setEos([]); setEoId(""); }
    })();
  }, [goalId]);

  useEffect(() => { setDynamicData({}); }, [eoId]);

  const selectedEO = eos.find((e) => e.id === eoId);
  const outcomeType = selectedEO?.outcome_type || "generic";
  const fields: FieldDef[] = registry[outcomeType]?.checkin_fields || [];

  const onSave = async () => {
    setError(null);
    if (!eoId) { setError("Add an expected outcome to this goal first."); return; }
    if (!title.trim()) { setError("Title is required."); return; }
    const missing = fields.filter((f) => f.required && (dynamicData[f.key] === undefined || dynamicData[f.key] === "" || dynamicData[f.key] === null)).map((f) => f.label);
    if (missing.length > 0) { setError(`Missing required fields: ${missing.join(", ")}`); return; }
    setBusy(true);
    try {
      const payload: any = {
        type: "goal", title: title.trim(), date, time, notes: notes.trim(),
        attachment, expected_outcome_id: eoId, source: "manual", data: dynamicData,
      };
      if (addFollowUp && followUpTitle.trim()) payload.follow_up_task = { title: followUpTitle.trim() };
      await api.createCheckin(payload);
      router.back();
    } catch (e: any) {
      setError(e?.message || "Could not save");
    } finally { setBusy(false); }
  };

  const setField = (k: string, v: any) => setDynamicData((prev) => ({ ...prev, [k]: v }));

  return (
    <SafeAreaView style={s.safe} edges={["top", "bottom"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} testID="goal-checkin-cancel" hitSlop={12}><Text style={s.cancel}>Cancel</Text></Pressable>
        <Text style={s.headerTitle}>Goal Check-in</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={s.label}>Goal</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {goals.map((g) => {
              const sel = goalId === g.id;
              return (
                <Pressable key={g.id} onPress={() => setGoalId(g.id)} style={[s.chip, sel && s.chipSelected]} testID={`goal-checkin-goal-chip-${g.id}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected]}>{g.title}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={s.label}>Expected Outcome</Text>
          {eos.length === 0 ? (
            <Text style={{ color: colors.onSurfaceSecondary, fontSize: 13 }}>No expected outcomes for this goal yet. Add one from the goal.</Text>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
              {eos.map((e) => {
                const sel = eoId === e.id;
                return (
                  <Pressable key={e.id} onPress={() => setEoId(e.id)} style={[s.chip, sel && s.chipSelected]} testID={`goal-checkin-eo-chip-${e.id}`}>
                    <Text style={[s.chipText, sel && s.chipTextSelected]}>{e.title}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}

          {selectedEO ? (
            <Text testID="goal-checkin-outcome-type-hint" style={{ marginTop: spacing.sm, fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1 }}>
              TYPE · {outcomeType.replace("_", " ").toUpperCase()}
            </Text>
          ) : null}

          <Text style={s.label}>Title</Text>
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="What did you do?" placeholderTextColor={colors.onSurfaceTertiary} testID="goal-checkin-title-input" />

          {/* Dynamic contextual fields for the selected Outcome Type */}
          {fields.map((f) => (
            <View key={f.key} testID={`dyn-field-${f.key}`}>
              <Text style={s.label}>{f.label}{f.required ? " *" : ""}</Text>
              {f.type === "select" && f.options ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                  {f.options.map((opt) => {
                    const sel = dynamicData[f.key] === opt;
                    return (
                      <Pressable key={opt} onPress={() => setField(f.key, opt)} style={[s.chip, sel && s.chipSelected]} testID={`dyn-field-${f.key}-opt-${opt}`}>
                        <Text style={[s.chipText, sel && s.chipTextSelected]}>{opt}</Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
              ) : f.type === "textarea" ? (
                <TextInput
                  style={s.notes}
                  value={dynamicData[f.key] || ""}
                  onChangeText={(v) => setField(f.key, v)}
                  multiline
                  textAlignVertical="top"
                  placeholder={f.label}
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID={`dyn-field-${f.key}-input`}
                />
              ) : (
                <TextInput
                  style={s.input}
                  value={dynamicData[f.key] !== undefined ? String(dynamicData[f.key]) : ""}
                  onChangeText={(v) => setField(f.key, f.type === "number" ? v.replace(/[^0-9.\-]/g, "") : v)}
                  keyboardType={f.type === "number" ? "numeric" : "default"}
                  placeholder={f.label}
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID={`dyn-field-${f.key}-input`}
                />
              )}
            </View>
          ))}

          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Date</Text>
              <TextInput style={s.input} value={date} onChangeText={setDate} testID="goal-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <TextInput style={s.input} value={time} onChangeText={setTime} testID="goal-checkin-time-input" />
            </View>
          </View>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="goal-checkin-notes-input" />

          <Text style={s.label}>Attachment (paste URL — placeholder)</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} testID="goal-checkin-attachment-input" />

          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.lg }}>
            <Text style={{ fontSize: 14, color: colors.onSurface }}>Create follow-up task</Text>
            <Switch value={addFollowUp} onValueChange={setAddFollowUp} testID="goal-checkin-followup-switch" />
          </View>
          {addFollowUp && (
            <TextInput style={[s.input, { marginTop: spacing.sm }]} value={followUpTitle} onChangeText={setFollowUpTitle} placeholder="Follow-up task title" placeholderTextColor={colors.onSurfaceTertiary} testID="goal-checkin-followup-title-input" />
          )}

          {error ? <Text style={s.errorText} testID="goal-checkin-error">{error}</Text> : null}
        </ScrollView>

        <View style={s.footer}>
          <Pressable style={[s.cta, busy && s.ctaDisabled]} onPress={onSave} disabled={busy} testID="goal-checkin-save-button">
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save check-in</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
