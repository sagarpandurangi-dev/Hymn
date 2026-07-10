import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors } from "@/src/lib/theme";
import { LearningJourneyForm } from "../add";

export default function EditLearningJourneyScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [initial, setInitial] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const j = await api.getLearningJourney(id!);
        setInitial({
          title: j.title,
          description: j.description,
          target_completion_date: j.target_completion_date,
          status: j.status,
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
    <LearningJourneyForm
      mode="edit"
      initial={initial}
      headerTitle="Edit journey"
      submitLabel="Save changes"
      testIDPrefix="edit-learn"
      onSubmit={async (payload) => {
        await api.updateLearningJourney(id!, payload);
        router.back();
      }}
    />
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
