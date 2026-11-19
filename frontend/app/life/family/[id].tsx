import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { formatINR } from "@/src/lib/finance/format";
import { agoText, CIRCLES, dayLine, kindLabel, niceDate, relLabel } from "@/src/lib/people";
import { colors, spacing } from "@/src/lib/theme";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const md = (s?: string) => { if (!s) return ""; const p = s.split("-").map(Number); const [m, d] = p.length === 3 ? [p[1], p[2]] : [p[0], p[1]]; return `${d} ${MONTHS[m - 1]}${p.length === 3 ? ` ${p[0]}` : ""}`; };
const mins = (n?: number) => (!n ? "" : n >= 60 ? `${Math.round((n / 60) * 10) / 10}h` : `${n}m`);

export default function PersonScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<any>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setP(await api.getPerson(String(id))); } catch (e) { setError((e as ApiError).message || "Couldn't load."); }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const removeMoment = (m: any) => {
    const run = async () => {
      try { await api.deleteMoment(m.id); await load(); } catch (e) { setError((e as ApiError).message || "Couldn't delete."); }
    };
    if (Platform.OS === "web") { if (window.confirm("Delete this moment?")) run(); return; }
    Alert.alert("Delete moment", "Delete this moment?", [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: run }]);
  };

  if (!p) {
    return (
      <SafeAreaView style={hs.safe} edges={["top", "bottom"]}>
        <HealthHeader title="Person" testID="person" hidePerson />
        <View style={{ padding: spacing.lg }}>{error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />}</View>
      </SafeAreaView>
    );
  }
  const moments: any[] = (p.moments ?? []).slice(0, 50);

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="person-screen">
      <HealthHeader
        title={p.name}
        testID="person"
        hidePerson
        right={
          <Pressable onPress={() => router.push(`/life/family/edit?id=${p.id}` as any)} hitSlop={8} style={hs.iconBtn} testID="person-edit-open">
            <Ionicons name="create-outline" size={22} color={colors.onSurface} />
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={hs.scroll}>
        {error ? <Text style={hs.error}>{error}</Text> : null}
        <View style={hs.card} testID="person-details">
          <Text style={hs.muted}>{[relLabel(p.relation), CIRCLES.find((c) => c.code === p.circle)?.label].filter(Boolean).join(" · ")}</Text>
          {p.next_day ? <Text style={[hs.h, { fontSize: 16 }]} testID="person-next-day">{dayLine(p.next_day, false)}</Text> : null}
          {p.last_together ? <Text style={hs.body}>Last together {agoText(p.days_since)}</Text> : <Text style={hs.body}>No moments logged yet</Text>}
          {p.birthday ? <Text style={hs.body}>Birthday: {md(p.birthday)}{p.birthday_gift ? ` · gift ${formatINR(p.birthday_gift)}` : ""}</Text> : null}
          {(p.occasions ?? []).map((o: any, i: number) => (
            <Text key={i} style={hs.body}>{o.label}: {md(o.date)}{o.gift_budget ? ` · gift ${formatINR(o.gift_budget)}` : ""}</Text>
          ))}
          {p.keep_in_touch_days ? <Text style={hs.muted}>Gentle nudge after {p.keep_in_touch_days} days</Text> : null}
          {p.notes ? <Text style={[hs.body, { color: colors.onSurface }]}>{p.notes}</Text> : null}
        </View>

        <Pressable style={hs.primary} onPress={() => router.push(`/life/family/moment?ids=${p.id}` as any)} testID="person-log-moment">
          <Text style={hs.primaryText}>Log a moment with {p.name}</Text>
        </Pressable>

        <View style={{ gap: spacing.sm }}>
          <Text style={hs.section}>MOMENTS</Text>
          {moments.length === 0 ? <Text style={hs.muted}>Nothing logged yet.</Text> : (
            <View style={hs.card}>
              {moments.map((m, i) => (
                <View key={m.id} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, borderTopWidth: i ? 1 : 0, borderTopColor: colors.divider }} testID={`person-moment-${m.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>{kindLabel(m.kind)}{m.minutes ? ` · ${mins(m.minutes)}` : ""}</Text>
                    <Text style={hs.muted}>{[niceDate(m.date), m.note, (m.person_ids ?? []).length > 1 ? `with ${(m.person_ids.length - 1)} more` : ""].filter(Boolean).join(" · ")}</Text>
                  </View>
                  <Pressable onPress={() => removeMoment(m)} hitSlop={10} style={hs.iconBtn} accessibilityLabel="Delete moment" testID={`person-moment-delete-${m.id}`}>
                    <Ionicons name="trash-outline" size={18} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
