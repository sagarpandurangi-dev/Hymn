import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors } from "@/src/lib/theme";
import { TaskForm } from "../add";

export default function EditTaskScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [initial, setInitial] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const t = await api.getTask(id!);
        setInitial({
          title: t.title, due_date: t.due_date, priority: t.priority, status: t.status, notes: t.notes,
          origin: t.origin, expected_outcome_id: t.expected_outcome_id, project_id: t.project_id,
          assigned_to_type: (t as any).assigned_to_type || "self",
          assigned_to_name: (t as any).assigned_to_name || "",
          assigned_to_phone: (t as any).assigned_to_phone || "",
        });
      } finally { setLoading(false); }
    })();
  }, [id]);

  if (loading || !initial) {
    return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>;
  }
  return (
    <TaskForm
      mode="edit"
      initial={initial}
      headerTitle="Edit Task"
      submitLabel="Save changes"
      testIDPrefix="edit-task"
      onSubmit={async (payload) => { await api.updateTask(id!, payload); router.back(); }}
    />
  );
}
const s = StyleSheet.create({ safe: { flex: 1, backgroundColor: colors.surface }, center: { flex: 1, alignItems: "center", justifyContent: "center" } });
