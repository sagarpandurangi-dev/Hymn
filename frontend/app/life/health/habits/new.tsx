import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs, PhoneText } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

type Kinds = Record<string, { label: string; goals: string[]; unit: string }>;

export default function NewHabitScreen() {
  const router = useRouter();
  const [kinds, setKinds] = useState<Kinds | null>(null);
  const [plans, setPlans] = useState<any[]>([]);
  const [kind, setKind] = useState("");
  const [goal, setGoal] = useState("");
  const [baseline, setBaseline] = useState("");
  const [target, setTarget] = useState("");
  const [cost, setCost] = useState("");
  const [forWhat, setForWhat] = useState("");
  const [planId, setPlanId] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<any>(null);

  useEffect(() => {
    api.getHabitKinds().then(setKinds).catch((e: ApiError) => setError(e.message || "Couldn't load the list."));
    api.listLifePlans().then((r: any) => setPlans(Array.isArray(r) ? r : r?.items ?? [])).catch(() => setPlans([]));
  }, []);

  const k = kind && kinds ? kinds[kind] : null;
  const pickKind = (code: string) => {
    setKind(code);
    const goals = kinds?.[code]?.goals ?? [];
    setGoal(goals.length === 1 ? goals[0] : goals.includes(goal) ? goal : "");
    setIsPrivate(code === "other");
  };

  const save = async () => {
    setError("");
    if (!kind) { setError("Pick what you'd like to change."); return; }
    if (!goal) { setError("Choose quit or cut down."); return; }
    if (!baseline) { setError("Roughly how much on a usual day? A guess is fine."); return; }
    if (goal === "cut_down" && !target) { setError("What would feel like a good amount a day?"); return; }
    if (!forWhat.trim() && !planId) { setError("Add what this is for — it helps when it's hard."); return; }
    const payload: Record<string, any> = { kind, goal, baseline_per_day: Number(baseline), private: isPrivate };
    if (goal === "cut_down") payload.target_per_day = Number(target);
    if (cost) payload.cost_per_unit = cost;
    if (planId) payload.serves_plan_id = planId;
    if (forWhat.trim()) payload.for_what = forWhat.trim();
    setBusy(true);
    try {
      setSaved(await api.createHabit(payload));
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (saved) {
    return (
      <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="habit-saved">
        <HealthHeader title="You've started" testID="habit-saved" />
        <ScrollView contentContainerStyle={hs.scroll}>
          <View style={hs.card}>
            <Ionicons name="leaf-outline" size={24} color={colors.brandPrimary} />
            <Text style={hs.h}>{saved.label}</Text>
            {saved.serves?.title || saved.for_what ? <Text style={[hs.body, { color: colors.onSurface }]}>For: {saved.serves?.title ?? saved.for_what}</Text> : null}
          </View>
          {saved.support ? (
            <View style={hs.card} testID="habit-support">
              <Text style={hs.section}>SUPPORT</Text>
              <PhoneText text={saved.support} style={[hs.body, { color: colors.onSurface, fontSize: 16, lineHeight: 24 }]} />
            </View>
          ) : null}
          <Pressable style={hs.primary} onPress={() => router.replace(`/life/health/habits/${saved.id}` as any)} testID="habit-saved-open">
            <Text style={hs.primaryText}>Open my habit</Text>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="habit-new-screen">
      <HealthHeader title="Add a habit" testID="habit-new" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          {!kinds ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
            <View>
              <Text style={hs.label}>What would you like to change?</Text>
              <View style={hs.chipRow}>
                {Object.entries(kinds).map(([code, v]) => (
                  <Pressable key={code} style={[hs.chip, kind === code && hs.chipOn]} onPress={() => pickKind(code)} testID={`habit-kind-${code}`}>
                    <Text style={[hs.chipText, kind === code && hs.chipTextOn]}>{v.label}</Text>
                  </Pressable>
                ))}
              </View>

              {k ? (
                <>
                  <Text style={hs.label}>Goal</Text>
                  <View style={hs.chipRow}>
                    {k.goals.map((g) => (
                      <Pressable key={g} style={[hs.chip, goal === g && hs.chipOn]} onPress={() => setGoal(g)} testID={`habit-goal-${g}`}>
                        <Text style={[hs.chipText, goal === g && hs.chipTextOn]}>{g === "quit" ? "Quit" : "Cut down"}</Text>
                      </Pressable>
                    ))}
                  </View>

                  <Text style={hs.label}>Usual amount a day ({k.unit})</Text>
                  <TextInput style={hs.input} value={baseline} onChangeText={(v) => setBaseline(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="A rough guess is fine" placeholderTextColor={colors.onSurfaceTertiary} testID="habit-baseline" />
                  {goal === "cut_down" ? (
                    <>
                      <Text style={hs.label}>Aim for a day ({k.unit})</Text>
                      <TextInput style={hs.input} value={target} onChangeText={(v) => setTarget(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="e.g. half of now" placeholderTextColor={colors.onSurfaceTertiary} testID="habit-target" />
                    </>
                  ) : null}
                  <Text style={hs.label}>Cost per {k.unit.split(" ")[0].replace(/s$/, "")} (₹, optional)</Text>
                  <TextInput style={hs.input} value={cost} onChangeText={(v) => setCost(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="e.g. 17" placeholderTextColor={colors.onSurfaceTertiary} testID="habit-cost" />

                  <Text style={hs.label}>What life is this for?</Text>
                  <TextInput style={hs.input} value={forWhat} onChangeText={setForWhat} placeholder="e.g. Keeping up with my kids" placeholderTextColor={colors.onSurfaceTertiary} testID="habit-for-what" />
                  {plans.length > 0 ? (
                    <>
                      <Text style={[hs.muted, { marginTop: spacing.sm }]}>Or tie it to one of your plans</Text>
                      <View style={[hs.chipRow, { marginTop: spacing.xs }]}>
                        {plans.map((p) => (
                          <Pressable key={p.id} style={[hs.chip, planId === p.id && hs.chipOn]} onPress={() => setPlanId(planId === p.id ? "" : p.id)} testID={`habit-plan-${p.id}`}>
                            <Text style={[hs.chipText, planId === p.id && hs.chipTextOn]} numberOfLines={1}>{p.title}</Text>
                          </Pressable>
                        ))}
                      </View>
                    </>
                  ) : null}

                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48, marginTop: spacing.md }}>
                    <View style={{ flex: 1 }}>
                      <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>Private</Text>
                      <Text style={hs.muted}>Kept out of summaries and shared views</Text>
                    </View>
                    <Switch value={isPrivate} onValueChange={setIsPrivate} testID="habit-private" />
                  </View>
                </>
              ) : null}

              {error ? <Text style={[hs.error, { marginTop: spacing.md }]} testID="habit-new-error">{error}</Text> : null}
              <Pressable style={[hs.primary, { marginTop: spacing.xl }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="habit-save">
                {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Start</Text>}
              </Pressable>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
