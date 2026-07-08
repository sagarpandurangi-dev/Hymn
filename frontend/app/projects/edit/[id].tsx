import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors } from "@/src/lib/theme";
import { ProjectForm } from "../add";

export default function EditProjectScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [initial, setInitial] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const p = await api.getProject(id!);
        setInitial({ title: p.title, description: p.description, status: p.status, start_date: p.start_date, target_end_date: p.target_end_date, notes: p.notes });
      } finally { setLoading(false); }
    })();
  }, [id]);

  if (loading || !initial) {
    return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>;
  }
  return (
    <ProjectForm
      initial={initial}
      headerTitle="Edit Project"
      submitLabel="Save changes"
      testIDPrefix="edit-project"
      onSubmit={async (payload) => { await api.updateProject(id!, payload); router.back(); }}
    />
  );
}
const s = StyleSheet.create({ safe: { flex: 1, backgroundColor: colors.surface }, center: { flex: 1, alignItems: "center", justifyContent: "center" } });
