import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { showToast } from "@/src/lib/toast";
import { colors, spacing } from "@/src/lib/theme";

export default function HealthDeleteScreen() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await api.deleteAllHealthData();
      showToast("Your health data has been deleted.");
      router.dismissAll?.();
      router.replace("/(tabs)/life" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete right now. Try again.");
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-delete-screen">
      <HealthHeader title="Delete health data" testID="health-delete" />
      <ScrollView contentContainerStyle={hs.scroll}>
        <View style={hs.card}>
          <Text style={hs.h}>This removes everything health-related</Text>
          <Text style={hs.body}>Your profile, daily logs and readings will be deleted from Hymn. This can&apos;t be undone. The rest of Hymn stays as it is.</Text>
          <Text style={hs.body}>You can set Health up again any time.</Text>
        </View>
        {error ? <Text style={hs.error}>{error}</Text> : null}
        <View style={{ gap: spacing.sm }}>
          <Pressable style={[hs.primary, { backgroundColor: colors.error }, busy && { opacity: 0.5 }]} onPress={remove} disabled={busy} testID="health-delete-confirm">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Delete all my health data</Text>}
          </Pressable>
          <Pressable style={hs.secondary} onPress={() => router.back()} disabled={busy} testID="health-delete-cancel">
            <Text style={hs.secondaryText}>Keep my data</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
