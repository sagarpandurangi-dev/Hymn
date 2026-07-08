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

type Project = { id: string; title: string };
type Task = { id: string; title: string };

export default function ProjectCheckinScreen() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [taskId, setTaskId] = useState<string>("");
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
        const ps = await api.listProjects();
        setProjects(ps.map((p) => ({ id: p.id, title: p.title })));
        if (ps.length > 0) setProjectId(ps[0].id);
      } catch { /* ignore */ }
    })();
  }, []);

  useEffect(() => {
    if (!projectId) { setTasks([]); return; }
    (async () => {
      try {
        const all = await api.listTasks();
        setTasks(all.filter((t) => t.project_id === projectId).map((t) => ({ id: t.id, title: t.title })));
        setTaskId("");
      } catch { setTasks([]); }
    })();
  }, [projectId]);

  const onSave = async () => {
    setError(null);
    if (!projectId) { setError("Create a project first."); return; }
    if (!title.trim()) { setError("Title is required."); return; }
    setBusy(true);
    try {
      const payload: any = { type: "project", title: title.trim(), date, time, notes: notes.trim(), attachment, project_id: projectId, source: "manual" };
      if (taskId) payload.task_id = taskId;
      if (addFollowUp && followUpTitle.trim()) payload.follow_up_task = { title: followUpTitle.trim() };
      await api.createCheckin(payload);
      router.back();
    } catch (e: any) { setError(e?.message || "Could not save"); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top", "bottom"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} testID="project-checkin-cancel" hitSlop={12}><Text style={s.cancel}>Cancel</Text></Pressable>
        <Text style={s.headerTitle}>Project Check-in</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.flex}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={s.label}>Project</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
            {projects.map((p) => {
              const sel = projectId === p.id;
              return (
                <Pressable key={p.id} onPress={() => setProjectId(p.id)} style={[s.chip, sel && s.chipSelected]} testID={`project-checkin-project-chip-${p.id}`}>
                  <Text style={[s.chipText, sel && s.chipTextSelected]}>{p.title}</Text>
                </Pressable>
              );
            })}
          </ScrollView>

          {tasks.length > 0 && (
            <>
              <Text style={s.label}>Optional Task</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
                <Pressable onPress={() => setTaskId("")} style={[s.chip, taskId === "" && s.chipSelected]} testID="project-checkin-task-chip-none">
                  <Text style={[s.chipText, taskId === "" && s.chipTextSelected]}>None</Text>
                </Pressable>
                {tasks.map((t) => {
                  const sel = taskId === t.id;
                  return (
                    <Pressable key={t.id} onPress={() => setTaskId(t.id)} style={[s.chip, sel && s.chipSelected]} testID={`project-checkin-task-chip-${t.id}`}>
                      <Text style={[s.chipText, sel && s.chipTextSelected]}>{t.title}</Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </>
          )}

          <Text style={s.label}>Title</Text>
          <TextInput style={s.titleInput} value={title} onChangeText={setTitle} placeholder="What did you do?" placeholderTextColor={colors.onSurfaceTertiary} testID="project-checkin-title-input" />

          <View style={{ flexDirection: "row", gap: spacing.md }}>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Date</Text>
              <TextInput style={s.input} value={date} onChangeText={setDate} testID="project-checkin-date-input" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>Time</Text>
              <TextInput style={s.input} value={time} onChangeText={setTime} testID="project-checkin-time-input" />
            </View>
          </View>

          <Text style={s.label}>Notes</Text>
          <TextInput style={s.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" testID="project-checkin-notes-input" />

          <Text style={s.label}>Attachment (paste URL — placeholder)</Text>
          <TextInput style={s.input} value={attachment} onChangeText={setAttachment} placeholder="Optional" placeholderTextColor={colors.onSurfaceTertiary} testID="project-checkin-attachment-input" />

          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.lg }}>
            <Text style={{ fontSize: 14, color: colors.onSurface }}>Create follow-up task</Text>
            <Switch value={addFollowUp} onValueChange={setAddFollowUp} testID="project-checkin-followup-switch" />
          </View>
          {addFollowUp && (
            <TextInput style={[s.input, { marginTop: spacing.sm }]} value={followUpTitle} onChangeText={setFollowUpTitle} placeholder="Follow-up task title" placeholderTextColor={colors.onSurfaceTertiary} testID="project-checkin-followup-title-input" />
          )}

          {error ? <Text style={s.errorText} testID="project-checkin-error">{error}</Text> : null}
        </ScrollView>

        <View style={s.footer}>
          <Pressable style={[s.cta, busy && s.ctaDisabled]} onPress={onSave} disabled={busy} testID="project-checkin-save-button">
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save check-in</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
