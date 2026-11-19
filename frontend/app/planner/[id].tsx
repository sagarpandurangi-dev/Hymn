import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import PlanCard from "@/src/components/planner/PlanCard";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

const confirmDrop = (ok: () => void) => {
  if (Platform.OS === "web") { if (window.confirm("Drop this plan?")) ok(); return; }
  Alert.alert("Drop this plan?", "It will be removed from your plans.", [{ text: "Cancel", style: "cancel" }, { text: "Drop", style: "destructive", onPress: ok }]);
};

export default function PlanDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useFocusEffect(useCallback(() => {
    api.getLifePlan(String(id)).then(setPlan).catch((e: ApiError) => setError(e.message || "Couldn't load this plan."));
  }, [id]));

  const drop = () => confirmDrop(async () => {
    setBusy(true);
    setError("");
    try {
      await api.deleteLifePlan(String(id));
      if (router.canGoBack()) router.back();
      else router.replace("/planner/plans" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't drop this plan.");
      setBusy(false);
    }
  });

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="plan-detail-screen">
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/planner/plans" as any))} hitSlop={12} style={styles.iconBtn} testID="plan-detail-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Plan</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        {!plan ? (error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
          <>
            <PlanCard plan={plan} onChanged={setPlan} />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable style={[styles.drop, busy && { opacity: 0.5 }]} onPress={drop} disabled={busy} testID="plan-drop">
              {busy ? <ActivityIndicator color={colors.error} /> : <Text style={styles.dropText}>Drop this plan</Text>}
            </Pressable>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 24, fontWeight: "700", color: colors.onSurface },
  scroll: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxxl },
  drop: { minHeight: 48, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.error, alignItems: "center", justifyContent: "center" },
  dropText: { color: colors.error, fontSize: 15, fontWeight: "700" },
  error: { fontSize: 13, color: colors.error },
});
