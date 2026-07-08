import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors } from "@/src/lib/theme";
import { EOForm } from "../add";

export default function EditExpectedOutcomeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [initial, setInitial] = useState<any>(null);
  const [goalId, setGoalId] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const eo = await api.getExpectedOutcome(id!);
        setInitial(eo);
        setGoalId(eo.goal_id);
      } finally { setLoading(false); }
    })();
  }, [id]);

  if (loading || !initial) return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>;

  return (
    <EOForm
      goalId={goalId}
      initial={initial}
      headerTitle="Edit Outcome"
      submitLabel="Save changes"
      testIDPrefix="edit-eo"
      onSubmit={async (payload) => { await api.updateExpectedOutcome(id!, payload); router.back(); }}
    />
  );
}
const s = StyleSheet.create({ safe: { flex: 1, backgroundColor: colors.surface }, center: { flex: 1, alignItems: "center", justifyContent: "center" } });
