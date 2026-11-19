import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import { HealthHeader, hs, RedFlags } from "@/src/components/health/ui";
import { showToast } from "@/src/lib/toast";
import { colors, spacing } from "@/src/lib/theme";

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const FACES = ["😣", "🙁", "😐", "🙂", "😄"];

function Faces({ label, hint, value, onChange, testID }: { label: string; hint?: string; value?: number; onChange: (v?: number) => void; testID: string }) {
  return (
    <View>
      <Text style={hs.label}>{label}{hint ? <Text style={hs.muted}>  {hint}</Text> : null}</Text>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        {FACES.map((f, i) => {
          const n = i + 1;
          const on = value === n;
          return (
            <Pressable key={n} onPress={() => onChange(on ? undefined : n)} style={[{ width: 56, height: 56, borderRadius: 28, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: on ? colors.brandPrimary : "transparent", backgroundColor: on ? colors.brandTertiary : colors.surfaceSecondary }]} accessibilityLabel={`${label} ${n} of 5`} testID={`${testID}-${n}`}>
              <Text style={{ fontSize: 26 }}>{f}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function Pick({ label, options, value, onChange, testID }: { label: string; options: { v: number; label: string }[]; value?: number; onChange: (v?: number) => void; testID: string }) {
  return (
    <View>
      <Text style={hs.label}>{label}</Text>
      <View style={hs.chipRow}>
        {options.map((o) => {
          const on = value === o.v;
          return (
            <Pressable key={o.v} style={[hs.chip, on && hs.chipOn]} onPress={() => onChange(on ? undefined : o.v)} testID={`${testID}-${o.v}`}>
              <Text style={[hs.chipText, on && hs.chipTextOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const NUMBERS: { key: string; label: string; placeholder: string; decimal?: boolean }[] = [
  { key: "sleep_hours", label: "Sleep (hours)", placeholder: "7.5", decimal: true },
  { key: "steps", label: "Steps", placeholder: "6000" },
  { key: "active_minutes", label: "Brisk activity (minutes)", placeholder: "30" },
  { key: "veg_fruit_portions", label: "Vegetables & fruit (portions)", placeholder: "5" },
  { key: "protein_servings", label: "Protein servings", placeholder: "3" },
  { key: "sugary_items", label: "Sweets or sugary drinks", placeholder: "0" },
  { key: "outside_meals", label: "Outside or fried meals", placeholder: "0" },
  { key: "water_glasses", label: "Glasses of water", placeholder: "8" },
];

export default function HealthDailyScreen() {
  const router = useRouter();
  const [symptomOptions, setSymptomOptions] = useState<Record<string, string>>({});
  const [faces, setFaces] = useState<Record<string, number | undefined>>({});
  const [bowel, setBowel] = useState<number | undefined>();
  const [strength, setStrength] = useState<number | undefined>();
  const [nums, setNums] = useState<Record<string, string>>({});
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [showSymptoms, setShowSymptoms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    api.getHealthOptions().then((o) => setSymptomOptions(o?.symptoms ?? {})).catch(() => setSymptomOptions({}));
  }, []);

  const save = async () => {
    setError("");
    const payload: Record<string, any> = { date: todayIso() };
    Object.entries(faces).forEach(([k, v]) => { if (v != null) payload[k] = v; });
    if (bowel != null) payload.bowel = bowel;
    if (strength != null) payload.strength_session = strength;
    Object.entries(nums).forEach(([k, v]) => { if (v !== "" && v != null) payload[k] = Number(v); });
    if (symptoms.length) payload.symptoms = symptoms;
    if (Object.keys(payload).length === 1) { setError("Fill in anything you like — even one thing helps."); return; }
    setBusy(true);
    try {
      const res = await api.logHealthDaily(payload);
      if (res?.red_flags?.length || res?.rules_reviewed === false) setResult(res);
      else {
        showToast("Saved. Thanks for checking in.");
        if (router.canGoBack()) router.back(); else router.replace("/life/health" as any);
      }
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-daily-result">
        <HealthHeader title="Today" testID="health-daily" />
        <ScrollView contentContainerStyle={hs.scroll}>
          <RedFlags flags={result.red_flags ?? []} />
          {result.rules_reviewed === false ? <DraftNote /> : null}
          <Text style={hs.body}>Your log for today is saved.</Text>
          <Pressable style={hs.secondary} onPress={() => (router.canGoBack() ? router.back() : router.replace("/life/health" as any))} testID="health-daily-done">
            <Text style={hs.secondaryText}>Back to Health</Text>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-daily-screen">
      <HealthHeader title="Today" testID="health-daily" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <Text style={hs.body}>About 30 seconds. Fill in only what you know — skip the rest.</Text>
          <View>
            <Faces label="Energy" value={faces.energy} onChange={(v) => setFaces({ ...faces, energy: v })} testID="daily-energy" />
            <Faces label="Mood" value={faces.mood} onChange={(v) => setFaces({ ...faces, mood: v })} testID="daily-mood" />
            <Faces label="Stress" hint="😄 calm · 😣 a lot" value={faces.stress != null ? 6 - faces.stress : undefined} onChange={(v) => setFaces({ ...faces, stress: v != null ? 6 - v : undefined })} testID="daily-stress" />
            <Faces label="Tummy" value={faces.digestion} onChange={(v) => setFaces({ ...faces, digestion: v })} testID="daily-digestion" />
            <Pick label="Bowel movement" options={[{ v: 0, label: "None" }, { v: 1, label: "Hard" }, { v: 2, label: "Easy" }]} value={bowel} onChange={setBowel} testID="daily-bowel" />
            <Pick label="Strength sessions" options={[0, 1, 2, 3].map((n) => ({ v: n, label: String(n) }))} value={strength} onChange={setStrength} testID="daily-strength" />
          </View>

          <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }}>
            {NUMBERS.map((n) => (
              <View key={n.key} style={{ width: "48%" }}>
                <Text style={hs.label} numberOfLines={1}>{n.label}</Text>
                <TextInput
                  style={hs.input}
                  value={nums[n.key] ?? ""}
                  onChangeText={(v) => setNums({ ...nums, [n.key]: v.replace(n.decimal ? /[^0-9.]/g : /[^0-9]/g, "") })}
                  keyboardType={n.decimal ? "decimal-pad" : "number-pad"}
                  placeholder={n.placeholder}
                  placeholderTextColor={colors.onSurfaceTertiary}
                  testID={`daily-${n.key}`}
                />
              </View>
            ))}
          </View>

          <View style={hs.card}>
            <Pressable style={{ flexDirection: "row", alignItems: "center", minHeight: 44, gap: spacing.sm }} onPress={() => setShowSymptoms(!showSymptoms)} testID="daily-symptoms-toggle">
              <Text style={[hs.body, { flex: 1, color: colors.onSurface, fontWeight: "600" }]}>Anything unusual today?</Text>
              <Ionicons name={showSymptoms ? "chevron-up" : "chevron-down"} size={18} color={colors.onSurfaceSecondary} />
            </Pressable>
            {showSymptoms ? Object.entries(symptomOptions).map(([code, label]) => {
              const on = symptoms.includes(code);
              return (
                <Pressable key={code} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 }} onPress={() => setSymptoms(on ? symptoms.filter((x) => x !== code) : [...symptoms, code])} accessibilityRole="checkbox" accessibilityState={{ checked: on }} testID={`daily-symptom-${code}`}>
                  <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.brandPrimary : colors.onSurfaceSecondary} />
                  <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{label}</Text>
                </Pressable>
              );
            }) : null}
          </View>

          {error ? <Text style={hs.error} testID="daily-error">{error}</Text> : null}
          <Pressable style={[hs.primary, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="daily-save">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
