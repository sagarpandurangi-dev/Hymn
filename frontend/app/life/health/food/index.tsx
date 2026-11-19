import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { amt, MEALS, mealLabel, unitText } from "@/src/components/food/FoodBits";
import { colors, spacing } from "@/src/lib/theme";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const shift = (s: string, days: number) => { const [y, m, d] = s.split("-").map(Number); return iso(new Date(y, m - 1, d + days)); };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dayTitle = (s: string) => {
  const today = iso(new Date());
  if (s === today) return "Today";
  if (s === shift(today, -1)) return "Yesterday";
  const [, m, d] = s.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
};
const kcal = (n: any) => Math.round(Number(n) || 0).toLocaleString("en-IN");

const confirm = (body: string, ok: () => void) => {
  if (Platform.OS === "web") { if (window.confirm(body)) ok(); return; }
  Alert.alert("Delete meal", body, [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: ok }]);
};

function Portion({ label, value, testID }: { label: string; value: any; testID: string }) {
  return (
    <View style={{ width: "50%", paddingVertical: spacing.xs }} testID={testID}>
      <Text style={{ fontSize: 22, fontWeight: "700", color: colors.onSurface }}>{amt(Number(value) || 0)}</Text>
      <Text style={hs.muted}>{label}</Text>
    </View>
  );
}

export default function FoodDayScreen() {
  const router = useRouter();
  const [date, setDate] = useState(iso(new Date()));
  const [day, setDay] = useState<any>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [noConsent, setNoConsent] = useState(false);

  const load = useCallback(async (d: string) => {
    try {
      setDay(await api.getFoodDay(d));
      setError("");
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 403) setNoConsent(true);
      else setError(err.message || "Couldn't load your food.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(date); }, [load, date]));

  const meals: any[] = [...(day?.meals ?? [])].sort((a, b) => MEALS.findIndex((m) => m.code === a.meal) - MEALS.findIndex((m) => m.code === b.meal));
  const t = day?.totals ?? {};
  const p = t.portions ?? {};
  const cal = t.calories;
  const isToday = date === iso(new Date());

  const remove = (m: any) => confirm(`Delete this ${mealLabel(m.meal).toLowerCase()}?`, async () => {
    try {
      await api.deleteMeal(m.id);
      await load(date);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete. Try again.");
    }
  });

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="food-day-screen">
      <HealthHeader
        title="Food"
        testID="food-day"
        right={
          <Pressable onPress={() => router.push("/life/health/food/my-foods" as any)} hitSlop={8} style={[hs.chip, { minHeight: 36 }]} testID="food-open-my-foods">
            <Text style={hs.chipText}>My foods</Text>
          </Pressable>
        }
      />
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg }}>
        <Pressable onPress={() => setDate(shift(date, -1))} style={hs.iconBtn} testID="food-prev-day"><Ionicons name="chevron-back" size={20} color={colors.onSurface} /></Pressable>
        <Text style={[hs.h, { fontSize: 16 }]} testID="food-day-title">{dayTitle(date)}</Text>
        <Pressable onPress={() => setDate(shift(date, 1))} disabled={isToday} style={[hs.iconBtn, isToday && { opacity: 0.3 }]} testID="food-next-day"><Ionicons name="chevron-forward" size={20} color={colors.onSurface} /></Pressable>
      </View>
      <ScrollView contentContainerStyle={hs.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(date); setRefreshing(false); }} />}>
        {noConsent ? (
          <View style={hs.card} testID="food-needs-consent">
            <Text style={hs.h}>Set up Health first</Text>
            <Text style={hs.body}>Food is part of Health. Once you agree to Hymn storing your health data, you can log meals here.</Text>
            <Pressable style={hs.primary} onPress={() => router.replace("/life/health" as any)} testID="food-go-health">
              <Text style={hs.primaryText}>Set up Health</Text>
            </Pressable>
          </View>
        ) : !day ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
          <>
            {day.values_reviewed === false ? <DraftNote text="Food values are typical, pending a nutritionist's review" /> : null}
            {error ? <Text style={hs.error}>{error}</Text> : null}

            <View style={hs.card} testID="food-totals">
              <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
                <Portion label="Fruit & veg portions" value={p.veg_fruit_portions} testID="food-total-veg" />
                <Portion label="Protein servings" value={p.protein_servings} testID="food-total-protein" />
                <Portion label="Sweets" value={p.sugary_items} testID="food-total-sweets" />
                <Portion label="Outside / fried meals" value={p.outside_meals} testID="food-total-outside" />
              </View>
              {cal && meals.length > 0 ? (
                <View style={{ borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, gap: 4 }} testID="food-total-calories">
                  <Text style={[hs.body, { color: colors.onSurface }]}>Calories: about {kcal(cal.estimate)} ({kcal(cal.low)}–{kcal(cal.high)})</Text>
                  {cal.note ? <Text style={hs.muted}>{cal.note}</Text> : null}
                </View>
              ) : null}
            </View>

            <Pressable style={hs.primary} onPress={() => router.push(`/life/health/food/add?date=${date}` as any)} testID="food-add-meal">
              <Text style={hs.primaryText}>Add a meal</Text>
            </Pressable>

            {meals.length === 0 ? (
              <Text style={hs.body} testID="food-empty">Nothing logged{isToday ? " yet today" : " for this day"}. A rough note is plenty — it doesn&apos;t need to be exact.</Text>
            ) : meals.map((m) => (
              <View key={m.id} style={hs.card} testID={`food-meal-${m.id}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <Text style={[hs.h, { flex: 1 }]}>{mealLabel(m.meal)}{m.outside ? <Text style={hs.muted}>  · eaten out</Text> : null}</Text>
                  <Pressable onPress={() => remove(m)} hitSlop={10} style={hs.iconBtn} accessibilityLabel="Delete meal" testID={`food-meal-delete-${m.id}`}>
                    <Ionicons name="trash-outline" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
                {(m.items ?? []).map((it: any, i: number) => (
                  <View key={i} style={{ flexDirection: "row", gap: spacing.sm }}>
                    <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{it.name}</Text>
                    <Text style={hs.muted}>{it.not_counted ? "not counted" : unitText(Number(it.amount) || 1, it.unit)}</Text>
                  </View>
                ))}
              </View>
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
