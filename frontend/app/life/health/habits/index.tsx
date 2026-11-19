import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { freedLine, progressLine, reasonOf } from "@/src/lib/habits";
import { colors, spacing } from "@/src/lib/theme";

export default function HabitsScreen() {
  const router = useRouter();
  const [habits, setHabits] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.listHabits();
      setHabits(Array.isArray(r) ? r : []);
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your habits.");
      setHabits([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="habits-screen">
      <HealthHeader
        title="Habits to change"
        testID="habits"
        right={
          <Pressable onPress={() => router.push("/life/health/habits/new" as any)} hitSlop={8} style={[hs.chip, { minHeight: 36 }]} testID="habits-add">
            <Text style={hs.chipText}>+ Add</Text>
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={hs.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {error ? <Text style={hs.error}>{error}</Text> : null}
        {habits === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : habits.length === 0 ? (
          <View style={hs.card} testID="habits-empty">
            <Text style={hs.h}>Change one thing, for something you care about</Text>
            <Text style={hs.body}>Pick a habit you&apos;d like to quit or cut down, and tie it to the life you want. Slips are part of it — every day is a fresh start.</Text>
            <Pressable style={[hs.primary, { marginTop: spacing.sm }]} onPress={() => router.push("/life/health/habits/new" as any)} testID="habits-empty-add">
              <Text style={hs.primaryText}>Add a habit</Text>
            </Pressable>
          </View>
        ) : habits.map((h) => {
          const freed = freedLine(h.progress);
          return (
            <Pressable key={h.id} style={({ pressed }) => [hs.card, pressed && { opacity: 0.85 }]} onPress={() => router.push(`/life/health/habits/${h.id}` as any)} testID={`habit-row-${h.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Text style={[hs.h, { flex: 1 }]}>{h.label}{h.private ? <Text style={hs.muted}>  · private</Text> : null}</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
              </View>
              <Text style={hs.muted}>{h.goal === "quit" ? "Quitting" : "Cutting down"}</Text>
              {reasonOf(h) ? <Text style={[hs.body, { color: colors.onSurface }]}>For: {reasonOf(h)}</Text> : null}
              <Text style={hs.body} testID={`habit-progress-${h.id}`}>{progressLine(h.progress)}</Text>
              {freed ? <Text style={[hs.body, { color: colors.success, fontWeight: "600" }]}>{freed}</Text> : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}
