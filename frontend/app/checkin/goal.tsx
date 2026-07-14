import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Switch, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const nowDate = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const nowTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };

type Goal = { id: string; title: string };
type EO = { id: string; goal_id: string; title: string; outcome_type: string };
type Task = { id: string; title: string; status: string; expected_outcome_id: string | null };
type FieldDef = { key: string; label: string; type: string; required?: boolean; options?: string[] };

export default function GoalCheckinScreen() {
  const router = useRouter();
  const { user } = useAuth();
  // Route parameters — if either is present it locks its respective picker.
  // The "required check-ins" flow always passes goalId; a per-EO deep link
  // may additionally pass expectedOutcomeId.
  const params = useLocalSearchParams<{ goalId?: string; expectedOutcomeId?: string; taskId?: string }>();
  const preselectedGoalId = typeof params.goalId === "string" && params.goalId ? params.goalId : "";
  const preselectedEoId = typeof params.expectedOutcomeId === "string" && params.expectedOutcomeId
    ? params.expectedOutcomeId
    : "";
  const preselectedTaskId = typeof params.taskId === "string" && params.taskId ? params.taskId : "";
  const goalLocked = !!preselectedGoalId;
  const eoLocked = !!preselectedEoId;

  const [goals, setGoals] = useState<Goal[]>([]);
  const [eos, setEos] = useState<EO[]>([]);
  const [tasksForEo, setTasksForEo] = useState<Task[]>([]);
  const [goalId, setGoalId] = useState<string>(preselectedGoalId);
  const [eoId, setEoId] = useState<string>(preselectedEoId);
  const [taskId, setTaskId] = useState<string>(preselectedTaskId);
  const [completeTask, setCompleteTask] = useState<boolean>(false);
  const [registry, setRegistry] = useState<Record<string, { label: string; checkin_fields: FieldDef[] }>>({});
  const [dynamicData, setDynamicData] = useState<Record<string, any>>({});
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(nowDate());
  const [time, setTime] = useState(nowTime());
  const [notes, setNotes] = useState("");
  const [attachment, setAttachment] = useState("");
  const [addFollowUp, setAddFollowUp] = useState(false);
  const [followUpTitle, setFollowUpTitle] = useState("");
  // Money spent alongside this check-in. Optional. When set, the amount is
  // added to today's spending and subtracted from the money-position's
  // "available for flexible spending" for the current month + currency.
  const [moneySpent, setMoneySpent] = useState<string>("");
  const [moneyCurrency, setMoneyCurrency] = useState<string>(user?.portfolio_reporting_currency || "USD");
  const [currencyPickerOpen, setCurrencyPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [gs, reg] = await Promise.all([api.listGoals(), api.getOutcomeTypes()]);
        setGoals(gs.map((g) => ({ id: g.id, title: g.title })));
        setRegistry(reg.types as any);
        // Preserve current manual flow when no route params are supplied.
        if (!preselectedGoalId && gs.length > 0) setGoalId(gs[0].id);
      } catch { /* ignore */ }
    })();
  }, [preselectedGoalId]);

  useEffect(() => {
    if (!goalId) { setEos([]); return; }
    (async () => {
      try {
        const list = await api.listExpectedOutcomes(goalId);
        const mapped = list.map((x) => ({
          id: x.id,
          goal_id: x.goal_id,
          title: x.title,
          outcome_type: (x as any).outcome_type || "generic",
        }));
        setEos(mapped);
        if (eoLocked) {
          // Only accept the pre-selected EO if it actually belongs to this Goal.
          const matched = mapped.find((e) => e.id === preselectedEoId);
          setEoId(matched ? matched.id : "");
        } else if (mapped.length === 1) {
          // Exactly one EO -> auto-select. Covers the "required check-ins"
          // deep link where the caller only knows the Goal.
          setEoId(mapped[0].id);
        } else if (mapped.length > 1) {
          // Multiple EOs -> let the user pick, but scoped to this Goal only.
          setEoId((prev) => (mapped.some((e) => e.id === prev) ? prev : ""));
        } else {
          setEoId("");
        }
      } catch { setEos([]); setEoId(""); }
    })();
  }, [goalId, eoLocked, preselectedEoId]);

  useEffect(() => { setDynamicData({}); }, [eoId]);

  // Load tasks under the currently-selected EO so the user can attach the
  // check-in to a specific task. Only open tasks (todo | deferred) are
  // shown — completed ones don't need a check-in.
  useEffect(() => {
    if (!eoId) { setTasksForEo([]); return; }
    (async () => {
      try {
        // We fetch by parent Goal (the backend filters by EO belongings) and
        // then intersect on the selected EO client-side. This keeps us on the
        // existing api.listTasks shape without a new backend query param.
        const all = await api.listTasks({ goalId, includeCompleted: false });
        const filtered = all.filter((t: any) => t.expected_outcome_id === eoId);
        setTasksForEo(filtered.map((t: any) => ({
          id: t.id, title: t.title, status: t.status, expected_outcome_id: t.expected_outcome_id,
        })));
        // If the user deep-linked with taskId, keep it; otherwise clear.
        setTaskId((prev) => (filtered.some((t: any) => t.id === prev) ? prev : (preselectedTaskId && filtered.some((t: any) => t.id === preselectedTaskId) ? preselectedTaskId : "")));
      } catch { setTasksForEo([]); }
    })();
  }, [eoId, goalId, preselectedTaskId]);

  const selectedGoal = useMemo(() => goals.find((g) => g.id === goalId), [goals, goalId]);
  const selectedEO = eos.find((e) => e.id === eoId);
  const outcomeType = selectedEO?.outcome_type || "generic";
  const fields: FieldDef[] = registry[outcomeType]?.checkin_fields || [];

  const onSave = async () => {
    setError(null);
    if (!eoId) { setError("Add an expected outcome to this goal first."); return; }
    if (!title.trim()) { setError("Title is required."); return; }
    const missing = fields.filter((f) => f.required && (dynamicData[f.key] === undefined || dynamicData[f.key] === "" || dynamicData[f.key] === null)).map((f) => f.label);
    if (missing.length > 0) { setError(`Missing required fields: ${missing.join(", ")}`); return; }
    // Money spent input is optional. When provided, it must be a positive
    // decimal string and money_currency must be a 3-letter ISO 4217 code.
    const trimmedMoney = (moneySpent || "").trim();
    if (trimmedMoney && !/^\d+(\.\d+)?$/.test(trimmedMoney)) {
      setError("Money spent must be a positive number.");
      return;
    }
    if (trimmedMoney && !/^[A-Z]{3}$/.test(moneyCurrency)) {
      setError("Pick a currency for the money spent.");
      return;
    }
    setBusy(true);
    try {
      const payload: any = {
        type: "goal", title: title.trim(), date, time, notes: notes.trim(),
        attachment, expected_outcome_id: eoId, source: "manual", data: dynamicData,
      };
      if (taskId) {
        payload.task_id = taskId;
        // Only flip the linked task to `done` when the user opted in — a
        // check-in on a task is normally an *update*, not a completion.
        payload.complete_task = completeTask;
      }
      if (trimmedMoney) {
        payload.money_spent = trimmedMoney;
        payload.money_currency = moneyCurrency;
      }
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
          {goalLocked ? (
            <View style={s.readonlyRow} testID="goal-checkin-goal-readonly">
              <Text style={s.readonlyText} numberOfLines={2}>
                {selectedGoal?.title || "Loading goal…"}
              </Text>
            </View>
          ) : (
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
          )}

          <Text style={s.label}>Expected Outcome</Text>
          {eos.length === 0 ? (
            <Text style={{ color: colors.onSurfaceSecondary, fontSize: 13 }}>No expected outcomes for this goal yet. Add one from the goal.</Text>
          ) : eoLocked ? (
            <View style={s.readonlyRow} testID="goal-checkin-eo-readonly">
              <Text style={s.readonlyText} numberOfLines={2}>
                {selectedEO?.title || "Loading…"}
              </Text>
            </View>
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
              <DateTimeField mode="date" value={date} onChange={setDate} testID="goal-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <DateTimeField mode="time" value={time} onChange={setTime} testID="goal-checkin-time-input" />
            </View>
          </View>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="goal-checkin-notes-input" />

          <Text style={s.label}>Attachment (paste URL — placeholder)</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} testID="goal-checkin-attachment-input" />

          {/* --- Optional Task linkage --- */}
          {tasksForEo.length > 0 && (
            <>
              <Text style={s.label}>Update a task under this outcome (optional)</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                <Pressable
                  onPress={() => setTaskId("")}
                  style={[s.chip, taskId === "" && s.chipSelected]}
                  testID="goal-checkin-task-chip-none"
                >
                  <Text style={[s.chipText, taskId === "" && s.chipTextSelected]}>None</Text>
                </Pressable>
                {tasksForEo.map((t) => {
                  const sel = taskId === t.id;
                  return (
                    <Pressable
                      key={t.id}
                      onPress={() => setTaskId(t.id)}
                      style={[s.chip, sel && s.chipSelected]}
                      testID={`goal-checkin-task-chip-${t.id}`}
                    >
                      <Text style={[s.chipText, sel && s.chipTextSelected]} numberOfLines={1}>{t.title}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
              {!!taskId && (
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.sm }}>
                  <Text style={{ fontSize: 14, color: colors.onSurface }}>Mark this task complete</Text>
                  <Switch value={completeTask} onValueChange={setCompleteTask} testID="goal-checkin-complete-task-switch" />
                </View>
              )}
            </>
          )}

          {/* --- Optional Money Spent --- */}
          <Text style={s.label}>Money spent (optional)</Text>
          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <TextInput
                style={s.input}
                value={moneySpent}
                onChangeText={(v) => setMoneySpent(v.replace(/[^0-9.]/g, ""))}
                keyboardType="decimal-pad"
                placeholder="0"
                placeholderTextColor={colors.onSurfaceTertiary}
                testID="goal-checkin-money-input"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Pressable
                onPress={() => setCurrencyPickerOpen(true)}
                style={s.input}
                testID="goal-checkin-currency-select"
              >
                <Text style={{ fontSize: 15, color: colors.onSurface }}>{moneyCurrency}</Text>
              </Pressable>
            </View>
          </View>

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

      <CurrencyPickerModal
        visible={currencyPickerOpen}
        selected={moneyCurrency}
        onSelect={(c) => setMoneyCurrency(c)}
        onClose={() => setCurrencyPickerOpen(false)}
      />
    </SafeAreaView>
  );
}
