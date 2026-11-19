import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { agoText, CIRCLES, dayLine, relLabel } from "@/src/lib/people";
import { colors, spacing } from "@/src/lib/theme";

export default function FamilyHome() {
  const router = useRouter();
  const [summary, setSummary] = useState<any>(null);
  const [people, setPeople] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.getPeopleSummary(), api.listPeople()]);
      setSummary(s);
      setPeople(Array.isArray(p) ? p : []);
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your people.");
      setPeople((x) => x ?? []);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const hear: any[] = (summary?.might_like_to_hear_from_you ?? []).slice(0, 3);
  const coming: any[] = summary?.coming_up ?? [];
  const hours = Number(summary?.inner_circle_hours ?? 0);

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="family-home">
      <HealthHeader
        title="Family & friends"
        testID="family-home"
        hidePerson
        right={
          <Pressable onPress={() => router.push("/life/family/edit" as any)} hitSlop={8} style={[hs.chip, { minHeight: 36 }]} testID="family-add-person">
            <Text style={hs.chipText}>+ Add</Text>
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={hs.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {people === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : (
          <>
            {error ? <Text style={hs.error}>{error}</Text> : null}
            {people.length === 0 ? (
              <View style={hs.card} testID="family-empty">
                <Ionicons name="heart-outline" size={24} color={colors.brandPrimary} />
                <Text style={hs.h}>The people who matter</Text>
                <Text style={hs.body}>Add family and friends, their birthdays and the days that matter. Hymn gently reminds you when someone might like to hear from you.</Text>
                <Pressable style={[hs.primary, { marginTop: spacing.sm }]} onPress={() => router.push("/life/family/edit" as any)} testID="family-empty-add">
                  <Text style={hs.primaryText}>Add someone</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <View style={hs.card} testID="family-summary">
                  <Text style={hs.section}>THIS MONTH</Text>
                  <View style={{ flexDirection: "row" }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontSize: 24, fontWeight: "700", color: colors.onSurface }} testID="family-inner-hours">{hours.toLocaleString("en-IN", { maximumFractionDigits: 1 })} h</Text>
                      <Text style={hs.muted}>with your inner circle</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontSize: 24, fontWeight: "700", color: colors.onSurface }} testID="family-reached">{summary?.people_reached ?? 0}</Text>
                      <Text style={hs.muted}>people reached</Text>
                    </View>
                  </View>
                  {hear.length > 0 ? (
                    <View style={{ gap: 6, marginTop: spacing.sm }} testID="family-hear">
                      <Text style={[hs.body, { fontWeight: "700", color: colors.onSurface }]}>Might like to hear from you</Text>
                      {hear.map((h) => (
                        <Pressable key={h.person_id} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 40 }} onPress={() => router.push(`/life/family/${h.person_id}` as any)} testID={`family-hear-${h.person_id}`}>
                          <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{h.name}</Text>
                          <Text style={hs.muted}>{h.days_since != null ? `It's been ${h.days_since} days` : "Not logged yet"}</Text>
                        </Pressable>
                      ))}
                    </View>
                  ) : null}
                  {coming.length > 0 ? (
                    <View style={{ gap: 6, marginTop: spacing.sm }} testID="family-coming-up">
                      <Text style={[hs.body, { fontWeight: "700", color: colors.onSurface }]}>Coming up</Text>
                      {coming.slice(0, 4).map((c, i) => (
                        <Text key={i} style={hs.body}>{dayLine(c)}</Text>
                      ))}
                    </View>
                  ) : null}
                </View>

                <Pressable style={hs.primary} onPress={() => router.push("/life/family/moment" as any)} testID="family-log-moment">
                  <Text style={hs.primaryText}>Log a moment</Text>
                </Pressable>

                {CIRCLES.map((c) => {
                  const group = people.filter((p) => (p.circle ?? "wider") === c.code);
                  if (group.length === 0) return null;
                  return (
                    <View key={c.code} style={{ gap: spacing.sm }} testID={`family-circle-${c.code}`}>
                      <Text style={hs.section}>{c.label.toUpperCase()}</Text>
                      <View style={hs.card}>
                        {group.map((p, i) => (
                          <Pressable key={p.id} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 56, borderTopWidth: i ? 1 : 0, borderTopColor: colors.divider }} onPress={() => router.push(`/life/family/${p.id}` as any)} testID={`family-person-${p.id}`}>
                            <View style={{ flex: 1 }}>
                              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                                <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>{p.name}</Text>
                                {p.might_like_to_hear_from_you ? <View style={[hs.dot, { width: 8, height: 8, backgroundColor: colors.brandPrimary, opacity: 0.6 }]} testID={`family-soft-dot-${p.id}`} /> : null}
                              </View>
                              <Text style={hs.muted}>{[relLabel(p.relation), p.last_together ? `together ${agoText(p.days_since)}` : ""].filter(Boolean).join(" · ")}</Text>
                              {p.next_day ? <Text style={hs.muted}>{dayLine(p.next_day, false)}</Text> : null}
                            </View>
                            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
                          </Pressable>
                        ))}
                      </View>
                    </View>
                  );
                })}
              </>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
