/**
 * Food bits: search with "My foods" mixed in, − / + amount in halves.
 */
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api } from "@/src/lib/api";
import { hs } from "@/src/components/health/ui";
import { colors, radius, spacing } from "@/src/lib/theme";

export const MEALS = [
  { code: "breakfast", label: "Breakfast" },
  { code: "lunch", label: "Lunch" },
  { code: "dinner", label: "Dinner" },
  { code: "snack", label: "Snack" },
];
export const mealLabel = (c: string) => MEALS.find((m) => m.code === c)?.label ?? c;

export const amt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, ""));
/** "1 katori", "1.5 katori", "2 piece". */
export const unitText = (amount: number, unit?: string) => (unit ? `${amt(amount)} ${unit}` : amt(amount));

export function AmountStepper({ value, onChange, testID }: { value: number; onChange: (v: number) => void; testID: string }) {
  return (
    <View style={styles.stepper}>
      <Pressable style={styles.stepBtn} onPress={() => onChange(Math.max(0.5, value - 0.5))} disabled={value <= 0.5} hitSlop={6} accessibilityLabel="Less" testID={`${testID}-minus`}>
        <Ionicons name="remove" size={18} color={value <= 0.5 ? colors.onSurfaceTertiary : colors.onSurface} />
      </Pressable>
      <Text style={styles.stepVal} testID={`${testID}-value`}>{amt(value)}</Text>
      <Pressable style={styles.stepBtn} onPress={() => onChange(value + 0.5)} hitSlop={6} accessibilityLabel="More" testID={`${testID}-plus`}>
        <Ionicons name="add" size={18} color={colors.onSurface} />
      </Pressable>
    </View>
  );
}

export function FoodSearch({ onPick, autoFocus, initialQuery = "" }: { onPick: (food: any) => void; autoFocus?: boolean; initialQuery?: string }) {
  const [q, setQ] = useState(initialQuery);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.searchFoods(term)
        .then((r) => { if (alive) setResults(Array.isArray(r) ? r : []); })
        .catch(() => { if (alive) setResults([]); })
        .finally(() => { if (alive) setLoading(false); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  return (
    <View style={{ gap: spacing.sm }}>
      <View style={styles.searchBox}>
        <Ionicons name="search" size={18} color={colors.onSurfaceTertiary} />
        <TextInput style={styles.searchInput} value={q} onChangeText={setQ} placeholder="Search — dal, roti, poha, apple…" placeholderTextColor={colors.onSurfaceTertiary} autoFocus={autoFocus} autoCorrect={false} returnKeyType="search" testID="food-search-input" />
        {loading ? <ActivityIndicator size="small" color={colors.onSurfaceTertiary} /> : null}
      </View>
      {q.trim().length >= 2 && !loading && results.length === 0 ? <Text style={hs.muted}>Nothing found. Try another name, or use “Something else”.</Text> : null}
      {(q.trim().length >= 2 ? results : []).map((f) => (
        <Pressable key={f.id} style={({ pressed }) => [styles.result, pressed && { opacity: 0.8 }]} onPress={() => onPick(f)} testID={`food-result-${f.id}`}>
          <View style={{ flex: 1 }}>
            <Text style={styles.resultName}>{f.name}</Text>
            <Text style={hs.muted}>1 {f.unit}{f.custom ? " · My food" : ""}</Text>
          </View>
          <Ionicons name="add-circle-outline" size={22} color={colors.brandPrimary} />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  stepper: { flexDirection: "row", alignItems: "center", gap: 4 },
  stepBtn: { width: 36, height: 36, borderRadius: 18, borderWidth: 1, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  stepVal: { minWidth: 32, textAlign: "center", fontSize: 15, fontWeight: "700", color: colors.onSurface },
  searchBox: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.borderStrong, paddingHorizontal: spacing.md, backgroundColor: colors.surface },
  searchInput: { flex: 1, fontSize: 15, color: colors.onSurface, minHeight: 44 },
  result: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 52, paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  resultName: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
});
