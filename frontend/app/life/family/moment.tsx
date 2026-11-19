import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { MOMENT_KINDS, TIME_CHIPS, todayIso } from "@/src/lib/people";
import { showToast } from "@/src/lib/toast";
import { colors, radius, spacing } from "@/src/lib/theme";

export default function LogMomentScreen() {
  const { ids } = useLocalSearchParams<{ ids?: string }>();
  const router = useRouter();
  const [people, setPeople] = useState<any[]>([]);
  const [chosen, setChosen] = useState<string[]>(ids ? String(ids).split(",") : []);
  const [kind, setKind] = useState("call");
  const [minutes, setMinutes] = useState<number | null>(null);
  const [date, setDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listPeople().then((r) => setPeople(Array.isArray(r) ? r : [])).catch(() => setPeople([]));
  }, []);

  const save = async () => {
    setError("");
    if (chosen.length === 0) { setError("Pick who it was with."); return; }
    setBusy(true);
    try {
      const payload: any = { person_ids: chosen, date, kind };
      if (minutes) payload.minutes = minutes;
      if (note.trim()) payload.note = note.trim();
      await api.logMoment(payload);
      showToast("Moment saved.");
      if (router.canGoBack()) router.back(); else router.replace("/life/family" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="moment-screen">
      <HealthHeader title="Log a moment" testID="moment" hidePerson />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
            {MOMENT_KINDS.map((k) => {
              const on = kind === k.code;
              return (
                <Pressable key={k.code} style={{ width: "31.5%", minHeight: 72, borderRadius: radius.md, alignItems: "center", justifyContent: "center", gap: 4, backgroundColor: on ? colors.brandPrimary : colors.surfaceSecondary }} onPress={() => setKind(k.code)} testID={`moment-kind-${k.code}`}>
                  <Ionicons name={k.icon as any} size={22} color={on ? colors.onBrandPrimary : colors.onSurface} />
                  <Text style={{ fontSize: 13, fontWeight: "600", color: on ? colors.onBrandPrimary : colors.onSurface }}>{k.label}</Text>
                </Pressable>
              );
            })}
          </View>

          <View>
            <Text style={hs.label}>How long (optional)</Text>
            <View style={hs.chipRow}>
              {TIME_CHIPS.map((t) => (
                <Pressable key={t.minutes} style={[hs.chip, minutes === t.minutes && hs.chipOn]} onPress={() => setMinutes(minutes === t.minutes ? null : t.minutes)} testID={`moment-time-${t.minutes}`}>
                  <Text style={[hs.chipText, minutes === t.minutes && hs.chipTextOn]}>{t.label}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={hs.label}>With</Text>
            {people.length === 0 ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : (
              <View style={hs.chipRow}>
                {people.map((p) => {
                  const on = chosen.includes(p.id);
                  return (
                    <Pressable key={p.id} style={[hs.chip, on && hs.chipOn]} onPress={() => setChosen(on ? chosen.filter((x) => x !== p.id) : [...chosen, p.id])} testID={`moment-person-${p.id}`}>
                      <Text style={[hs.chipText, on && hs.chipTextOn]}>{p.name}</Text>
                    </Pressable>
                  );
                })}
              </View>
            )}

            <Text style={hs.label}>When</Text>
            <DateTimeField mode="date" value={date} onChange={setDate} testID="moment-date" />
            <Text style={hs.label}>Note (optional)</Text>
            <TextInput style={hs.input} value={note} onChangeText={setNote} placeholder="e.g. Talked about her garden" placeholderTextColor={colors.onSurfaceTertiary} testID="moment-note" />
          </View>

          {error ? <Text style={hs.error} testID="moment-error">{error}</Text> : null}
          <Pressable style={[hs.primary, busy && { opacity: 0.5 }]} onPress={save} disabled={busy || !date} testID="moment-save">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
