import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

const NUM_FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "kcal", label: "Calories (kcal)", required: true },
  { key: "protein_g", label: "Protein (g)" },
  { key: "carbs_g", label: "Carbs (g)" },
  { key: "fat_g", label: "Fat (g)" },
  { key: "fibre_g", label: "Fibre (g)" },
  { key: "veg_fruit_portions", label: "Fruit & veg portions" },
  { key: "protein_servings", label: "Protein servings" },
];

const str = (v: any) => (v == null || v === "" ? "" : String(v));

/** Turn a label reading into form values (fields the server may name slightly differently). */
const fromLabel = (raw?: string) => {
  try {
    const l = raw ? JSON.parse(raw) : null;
    if (!l) return null;
    return {
      name: str(l.name), unit: str(l.unit ?? l.serving ?? "serving"),
      kcal: str(l.kcal ?? l.calories), protein_g: str(l.protein_g), carbs_g: str(l.carbs_g), fat_g: str(l.fat_g), fibre_g: str(l.fibre_g),
      veg_fruit_portions: str(l.veg_fruit_portions), protein_servings: str(l.protein_servings),
      sugary: !!l.sugary, fried: !!l.fried,
    };
  } catch {
    return null;
  }
};

const confirmDelete = (name: string, ok: () => void) => {
  if (Platform.OS === "web") { if (window.confirm(`Delete “${name}” from My foods?`)) ok(); return; }
  Alert.alert("Delete food", `Delete “${name}” from My foods?`, [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: ok }]);
};

export default function MyFoodsScreen() {
  const { prefill } = useLocalSearchParams<{ prefill?: string }>();
  const pre = fromLabel(prefill);
  const [foods, setFoods] = useState<any[] | null>(null);
  const [open, setOpen] = useState(!!pre);
  const [form, setForm] = useState<Record<string, any>>(pre ?? { name: "", unit: "", sugary: false, fried: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.listMyFoods();
      setFoods(Array.isArray(r) ? r : []);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your foods.");
      setFoods([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setError("");
    if (!String(form.name ?? "").trim()) { setError("Give it a name."); return; }
    if (!String(form.unit ?? "").trim()) { setError("Add a unit, like “1 bar” or “1 katori”."); return; }
    if (form.kcal === "" || form.kcal == null) { setError("Add the calories for one unit."); return; }
    const payload: Record<string, any> = { name: form.name.trim(), unit: form.unit.trim(), sugary: !!form.sugary, fried: !!form.fried };
    NUM_FIELDS.forEach((f) => { payload[f.key] = Number(form[f.key] || 0); });
    setBusy(true);
    try {
      await api.addMyFood(payload);
      setForm({ name: "", unit: "", sugary: false, fried: false });
      setOpen(false);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const remove = (f: any) => confirmDelete(f.name, async () => {
    try {
      await api.deleteMyFood(f.id);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete. Try again.");
    }
  });

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="my-foods-screen">
      <HealthHeader title="My foods" testID="my-foods" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <Text style={hs.body}>Foods you add here show up in search when you log a meal.</Text>
          {error ? <Text style={hs.error} testID="my-foods-error">{error}</Text> : null}

          {open ? (
            <View style={hs.card} testID="my-food-form">
              <Text style={hs.h}>{pre ? "Save as my food" : "Add a food"}</Text>
              {pre ? <Text style={hs.muted}>Filled in from the label — check it before saving.</Text> : null}
              <Text style={hs.label}>Name</Text>
              <TextInput style={hs.input} value={form.name} onChangeText={(v) => set("name", v)} placeholder="e.g. Granola bar" placeholderTextColor={colors.onSurfaceTertiary} testID="my-food-name" />
              <Text style={hs.label}>Unit</Text>
              <TextInput style={hs.input} value={form.unit} onChangeText={(v) => set("unit", v)} placeholder="e.g. bar, katori, piece" placeholderTextColor={colors.onSurfaceTertiary} testID="my-food-unit" />
              <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }}>
                {NUM_FIELDS.map((f) => (
                  <View key={f.key} style={{ width: "48%" }}>
                    <Text style={hs.label} numberOfLines={1}>{f.label}</Text>
                    <TextInput style={hs.input} value={str(form[f.key])} onChangeText={(v) => set(f.key, v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={colors.onSurfaceTertiary} testID={`my-food-${f.key}`} />
                  </View>
                ))}
              </View>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48, marginTop: spacing.sm }}>
                <Text style={[hs.body, { color: colors.onSurface }]}>Sweet or sugary</Text>
                <Switch value={!!form.sugary} onValueChange={(v) => set("sugary", v)} testID="my-food-sugary" />
              </View>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48 }}>
                <Text style={[hs.body, { color: colors.onSurface }]}>Fried</Text>
                <Switch value={!!form.fried} onValueChange={(v) => set("fried", v)} testID="my-food-fried" />
              </View>
              <Pressable style={[hs.primary, { marginTop: spacing.md }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="my-food-save">
                {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
              </Pressable>
              <Pressable style={{ minHeight: 44, alignItems: "center", justifyContent: "center" }} onPress={() => setOpen(false)} testID="my-food-cancel">
                <Text style={hs.body}>Cancel</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable style={hs.secondary} onPress={() => setOpen(true)} testID="my-food-open-form">
              <Ionicons name="add" size={18} color={colors.onSurface} />
              <Text style={hs.secondaryText}>Add a food</Text>
            </Pressable>
          )}

          {foods === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : foods.length === 0 ? (
            <Text style={hs.muted} testID="my-foods-empty">No foods of your own yet.</Text>
          ) : (
            <View style={hs.card}>
              {foods.map((f) => (
                <View key={f.id} style={{ flexDirection: "row", alignItems: "center", minHeight: 52, gap: spacing.sm }} testID={`my-food-${f.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>{f.name}</Text>
                    <Text style={hs.muted}>1 {f.unit} · about {Math.round(Number(f.kcal) || 0)} kcal</Text>
                  </View>
                  <Pressable onPress={() => remove(f)} hitSlop={10} style={hs.iconBtn} accessibilityLabel={`Delete ${f.name}`} testID={`my-food-delete-${f.id}`}>
                    <Ionicons name="trash-outline" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
