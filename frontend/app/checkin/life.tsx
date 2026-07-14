import { useEffect, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Switch, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const nowDate = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const nowTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };

type Task = { id: string; title: string };

export default function LifeCheckinScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState<string>("");
  const [completeTask, setCompleteTask] = useState<boolean>(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(nowDate());
  const [time, setTime] = useState(nowTime());
  const [notes, setNotes] = useState("");
  const [attachment, setAttachment] = useState("");
  const [addFollowUp, setAddFollowUp] = useState(false);
  const [followUpTitle, setFollowUpTitle] = useState("");
  // Optional money spent alongside this check-in. Amount is a decimal string;
  // currency is ISO 4217 and defaults to the user's reporting currency.
  const [moneySpent, setMoneySpent] = useState<string>("");
  const [moneyCurrency, setMoneyCurrency] = useState<string>(user?.portfolio_reporting_currency || "USD");
  const [currencyPickerOpen, setCurrencyPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Any of the user's open tasks can be attached to a Life check-in —
        // there is no owning Goal/Project constraint for Life.
        const all = await api.listTasks({ includeCompleted: false });
        setTasks(all.map((t) => ({ id: t.id, title: t.title })));
      } catch { setTasks([]); }
    })();
  }, []);

  const onSave = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
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
      const payload: any = { type: "life", title: title.trim(), date, time, notes: notes.trim(), attachment, source: "manual" };
      if (taskId) {
        payload.task_id = taskId;
        // Task completion is opt-in — a Life check-in is normally an update
        // (or just a note); flip only when the user explicitly says so.
        payload.complete_task = completeTask;
      }
      if (trimmedMoney) {
        payload.money_spent = trimmedMoney;
        payload.money_currency = moneyCurrency;
      }
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
              <DateTimeField mode="date" value={date} onChange={setDate} testID="life-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <DateTimeField mode="time" value={time} onChange={setTime} testID="life-checkin-time-input" />
            </View>
          </View>

          {tasks.length > 0 && (
            <>
              <Text style={s.label}>Update a task (optional)</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                <Pressable
                  onPress={() => setTaskId("")}
                  style={[s.chip, taskId === "" && s.chipSelected]}
                  testID="life-checkin-task-chip-none"
                >
                  <Text style={[s.chipText, taskId === "" && s.chipTextSelected]}>None</Text>
                </Pressable>
                {tasks.map((t) => {
                  const sel = taskId === t.id;
                  return (
                    <Pressable
                      key={t.id}
                      onPress={() => setTaskId(t.id)}
                      style={[s.chip, sel && s.chipSelected]}
                      testID={`life-checkin-task-chip-${t.id}`}
                    >
                      <Text style={[s.chipText, sel && s.chipTextSelected]} numberOfLines={1}>{t.title}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
              {!!taskId && (
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.sm }}>
                  <Text style={{ fontSize: 14, color: colors.onSurface }}>Mark this task complete</Text>
                  <Switch value={completeTask} onValueChange={setCompleteTask} testID="life-checkin-complete-task-switch" />
                </View>
              )}
            </>
          )}

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="life-checkin-notes-input" />

          <Text style={s.label}>Attachment (paste URL — placeholder)</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} testID="life-checkin-attachment-input" />

          {/* --- Optional money spent --- */}
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
                testID="life-checkin-money-input"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Pressable
                onPress={() => setCurrencyPickerOpen(true)}
                style={s.input}
                testID="life-checkin-currency-select"
              >
                <Text style={{ fontSize: 15, color: colors.onSurface }}>{moneyCurrency}</Text>
              </Pressable>
            </View>
          </View>

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

      <CurrencyPickerModal
        visible={currencyPickerOpen}
        selected={moneyCurrency}
        onSelect={(c) => setMoneyCurrency(c)}
        onClose={() => setCurrencyPickerOpen(false)}
      />
    </SafeAreaView>
  );
}
