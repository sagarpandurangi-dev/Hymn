import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, spacing, TASK_PRIORITIES, TASK_STATUSES, TASK_ASSIGNMENT_TYPES } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";

type Project = { id: string; title: string };
type Goal = { id: string; title: string };
type EO = { id: string; goal_id: string; title: string };

const ORIGINS = ["standalone", "project", "expected_outcome"] as const;

type Props = {
  initial?: {
    title: string; due_date: string; priority: string; status: string; notes: string;
    origin: string; expected_outcome_id: string | null; project_id: string | null;
    assigned_to_type?: string; assigned_to_name?: string; assigned_to_phone?: string;
  } | null;
  mode: "add" | "edit";
  headerTitle: string;
  submitLabel: string;
  testIDPrefix: string;
  onSubmit: (payload: any) => Promise<void>;
};

export function TaskForm({ initial, mode, headerTitle, submitLabel, testIDPrefix, onSubmit }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState(initial?.title || "");
  const [dueDate, setDueDate] = useState(initial?.due_date || "");
  const [priority, setPriority] = useState(initial?.priority || "medium");
  const [status, setStatus] = useState(initial?.status || "todo");
  const [notes, setNotes] = useState(initial?.notes || "");
  const [origin, setOrigin] = useState(initial?.origin || "standalone");
  const [projectId, setProjectId] = useState<string>(initial?.project_id || "");
  const [goalId, setGoalId] = useState<string>("");
  const [eoId, setEoId] = useState<string>(initial?.expected_outcome_id || "");
  const [assignedType, setAssignedType] = useState<string>(initial?.assigned_to_type || "self");
  const [assignedName, setAssignedName] = useState<string>(initial?.assigned_to_name || "");
  const [assignedPhone, setAssignedPhone] = useState<string>(initial?.assigned_to_phone || "");
  const [projects, setProjects] = useState<Project[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [eos, setEos] = useState<EO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [ps, gs] = await Promise.all([api.listProjects(), api.listGoals()]);
        setProjects(ps.map((p) => ({ id: p.id, title: p.title })));
        setGoals(gs.map((g) => ({ id: g.id, title: g.title })));
      } catch { /* ignore */ }
    })();
  }, []);

  useEffect(() => {
    if (!goalId) { setEos([]); return; }
    (async () => {
      try {
        const list = await api.listExpectedOutcomes(goalId);
        setEos(list.map((x) => ({ id: x.id, goal_id: x.goal_id, title: x.title })));
      } catch { setEos([]); }
    })();
  }, [goalId]);

  const save = async () => {
    setError(null);
    if (!title.trim()) { setError("Title is required."); return; }
    if (mode === "add" && origin === "project" && !projectId) { setError("Choose a project."); return; }
    if (mode === "add" && origin === "expected_outcome" && !eoId) { setError("Choose a goal and expected outcome."); return; }
    if (assignedType === "external" && !assignedName.trim() && !assignedPhone.trim()) {
      setError("Enter a name or phone for the external assignee."); return;
    }
    setBusy(true);
    try {
      const payload: any = { title: title.trim(), due_date: dueDate.trim(), priority, status, notes: notes.trim() };
      payload.assigned_to_type = assignedType;
      payload.assigned_to_name = assignedType === "external" ? assignedName.trim() : "";
      payload.assigned_to_phone = assignedType === "external" ? assignedPhone.trim() : "";
      if (mode === "add") {
        payload.origin = origin;
        payload.expected_outcome_id = origin === "expected_outcome" ? eoId : null;
        payload.project_id = origin === "project" ? projectId : null;
      }
      await onSubmit(payload);
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
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="What needs doing?" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-title-input`} />

          {mode === "add" && (
            <>
              <Text style={s.label}>Origin</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                {ORIGINS.map((o) => {
                  const sel = origin === o;
                  const label = o === "expected_outcome" ? "Expected Outcome" : o.charAt(0).toUpperCase() + o.slice(1);
                  return (
                    <Pressable key={o} onPress={() => setOrigin(o)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-origin-chip-${o}`}>
                      <Text style={[s.chipText, sel && s.chipTextSelected]}>{label}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              {origin === "project" && (
                <>
                  <Text style={s.label}>Project</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                    {projects.map((p) => {
                      const sel = projectId === p.id;
                      return (
                        <Pressable key={p.id} onPress={() => setProjectId(p.id)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-project-chip-${p.id}`}>
                          <Text style={[s.chipText, sel && s.chipTextSelected]}>{p.title}</Text>
                        </Pressable>
                      );
                    })}
                  </ScrollView>
                </>
              )}

              {origin === "expected_outcome" && (
                <>
                  <Text style={s.label}>Goal</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                    {goals.map((g) => {
                      const sel = goalId === g.id;
                      return (
                        <Pressable key={g.id} onPress={() => setGoalId(g.id)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-goal-chip-${g.id}`}>
                          <Text style={[s.chipText, sel && s.chipTextSelected]}>{g.title}</Text>
                        </Pressable>
                      );
                    })}
                  </ScrollView>
                  <Text style={s.label}>Expected Outcome</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                    {eos.map((e) => {
                      const sel = eoId === e.id;
                      return (
                        <Pressable key={e.id} onPress={() => setEoId(e.id)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-eo-chip-${e.id}`}>
                          <Text style={[s.chipText, sel && s.chipTextSelected]}>{e.title}</Text>
                        </Pressable>
                      );
                    })}
                  </ScrollView>
                </>
              )}
            </>
          )}

          <Text style={s.label}>Due Date</Text>
          <TextInput style={s.input} value={dueDate} onChangeText={setDueDate} placeholder="YYYY-MM-DD (optional)" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-due-input`} />

          <Text style={s.label}>Priority</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {TASK_PRIORITIES.map((p) => {
              const sel = priority === p;
              return (
                <Pressable key={p} onPress={() => setPriority(p)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-priority-chip-${p}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected, { textTransform: "capitalize" }]}>{p}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={s.label}>Status</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {TASK_STATUSES.map((st) => {
              const sel = status === st;
              return (
                <Pressable key={st} onPress={() => setStatus(st)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-status-chip-${st}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected, { textTransform: "capitalize" }]}>{st}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID={`${testIDPrefix}-notes-input`} />

          <Text style={s.label}>Assigned To</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {TASK_ASSIGNMENT_TYPES.map((a) => {
              const sel = assignedType === a;
              return (
                <Pressable key={a} onPress={() => setAssignedType(a)} style={[s.chip, sel && s.chipSelected]} testID={`${testIDPrefix}-assign-chip-${a}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected, { textTransform: "capitalize" }]}>{a === "self" ? "Self" : "External"}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          {assignedType === "external" && (
            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={s.label}>Name</Text>
                <TextInput style={s.input} value={assignedName} onChangeText={setAssignedName} placeholder="e.g. Alex" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testIDPrefix}-assign-name-input`} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.label}>Phone</Text>
                <TextInput style={s.input} value={assignedPhone} onChangeText={setAssignedPhone} placeholder="+1 555 …" placeholderTextColor={colors.onSurfaceTertiary} keyboardType="phone-pad" testID={`${testIDPrefix}-assign-phone-input`} />
              </View>
            </View>
          )}

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

export default function AddTaskScreen() {
  const router = useRouter();
  return (
    <TaskForm
      mode="add"
      headerTitle="New Task"
      submitLabel="Create task"
      testIDPrefix="add-task"
      onSubmit={async (payload) => { await api.createTask(payload); router.back(); }}
    />
  );
}

// eslint keeps `spacing` used via s import
export const _ns = spacing.md;
