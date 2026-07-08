import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors } from "@/src/lib/theme";
import { GoalForm } from "../add";

export default function EditGoalScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [initial, setInitial] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const g = await api.getGoal(id!);
        setInitial({
          title: g.title,
          domain_id: g.domain_id,
          target_outcome: g.target_outcome,
          deadline: g.deadline,
          status: g.status,
          notes: g.notes,
        });
      } finally { setLoading(false); }
    })();
  }, [id]);

  if (loading || !initial) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>
    );
  }

  return (
    <GoalForm
      mode="edit"
      initial={initial}
      headerTitle="Edit Goal"
      submitLabel="Save changes"
      testIDPrefix="edit-goal"
      onSubmit={async (payload) => {
        await api.updateGoal(id!, payload);
        router.back();
      }}
    />
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
