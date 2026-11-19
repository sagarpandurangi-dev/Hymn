import { useCallback, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import HealthProfileForm from "@/src/components/health/HealthProfileForm";
import { HealthHeader, hs, RedFlags, statusColour } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

/** Metrics the 30-second daily log can fill in. */
export const DAILY_METRICS = ["energy", "mood", "stress", "digestion", "bowel", "sleep_hours", "steps", "active_minutes", "strength_session", "veg_fruit_portions", "protein_servings", "sugary_items", "outside_meals", "water_glasses"];

function Consent({ options, onSaved }: { options: any; onSaved: (p: any) => void }) {
  const [agreed, setAgreed] = useState(false);
  return (
    <>
      <View style={hs.card} testID="health-consent">
        <Text style={hs.h}>Before we start</Text>
        <View style={{ gap: spacing.sm }}>
          {[
            ["document-text-outline", "Hymn stores your answers and the readings you add — like sleep, steps or a blood test."],
            ["lock-closed-outline", "Nothing is shared with anyone."],
            ["trash-outline", "You can delete all of it any time, in one tap."],
          ].map(([icon, text]) => (
            <View key={text} style={{ flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" }}>
              <Ionicons name={icon as any} size={18} color={colors.brandPrimary} style={{ marginTop: 2 }} />
              <Text style={[hs.body, { flex: 1 }]}>{text}</Text>
            </View>
          ))}
        </View>
        <Pressable style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48 }} onPress={() => setAgreed(!agreed)} accessibilityRole="checkbox" accessibilityState={{ checked: agreed }} testID="health-consent-checkbox">
          <Ionicons name={agreed ? "checkbox" : "square-outline"} size={24} color={agreed ? colors.brandPrimary : colors.onSurfaceSecondary} />
          <Text style={[hs.body, { flex: 1, color: colors.onSurface, fontWeight: "600" }]}>I agree to Hymn storing my health data</Text>
        </Pressable>
      </View>
      {agreed ? (
        <View>
          <Text style={hs.h}>A little about you</Text>
          <Text style={hs.body}>This helps Hymn use the ranges that fit you. Skip anything you don&apos;t want to answer.</Text>
          <HealthProfileForm initial={null} options={options} saveLabel="Save and continue" onSaved={onSaved} />
        </View>
      ) : null}
    </>
  );
}

export default function HealthHome() {
  const router = useRouter();
  const [profile, setProfile] = useState<any>(null);
  const [options, setOptions] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [showAllMissing, setShowAllMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, o] = await Promise.all([api.getHealthProfile(), api.getHealthOptions().catch(() => null)]);
      setProfile(p);
      setOptions(o);
      if (p?.consent) {
        const [d, s] = await Promise.all([api.getHealthDashboard(), api.getHealthSuggestions().catch(() => [])]);
        setDash(d);
        setSuggestions((Array.isArray(s) ? s : s?.items ?? s?.suggestions ?? []).slice(0, 3));
      }
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your health right now.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const consent = !!profile?.consent;
  const missing: any[] = dash?.missing ?? [];
  const shownMissing = showAllMissing ? missing : missing.slice(0, 6);
  const seeDoctor: string[] = dash?.screening?.see_doctor_first_because ?? [];

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-home">
      <HealthHeader
        title="Health"
        testID="health-home"
        right={consent ? (
          <Pressable onPress={() => router.push("/life/health/settings" as any)} hitSlop={8} style={hs.iconBtn} testID="health-open-settings">
            <Ionicons name="settings-outline" size={22} color={colors.onSurface} />
          </Pressable>
        ) : undefined}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView
          contentContainerStyle={hs.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
        >
          {!profile ? (
            error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />
          ) : !consent ? (
            <Consent options={options} onSaved={() => load()} />
          ) : (
            <>
              <RedFlags flags={dash?.red_flags ?? []} />
              {dash?.rules_reviewed === false ? <DraftNote /> : null}
              {error ? <Text style={hs.error}>{error}</Text> : null}

              <Pressable style={hs.primary} onPress={() => router.push("/life/health/daily" as any)} testID="health-open-daily">
                <Text style={hs.primaryText}>Log today · 30 seconds</Text>
              </Pressable>
              <Pressable style={hs.secondary} onPress={() => router.push("/life/health/food" as any)} testID="health-open-food">
                <Ionicons name="restaurant-outline" size={18} color={colors.onSurface} />
                <Text style={hs.secondaryText}>Food</Text>
              </Pressable>

              {seeDoctor.length > 0 ? (
                <View style={hs.card} testID="health-see-doctor">
                  <Text style={hs.h}>Good to check with your doctor first</Text>
                  {seeDoctor.map((r, i) => <Text key={i} style={hs.body}>• {r}</Text>)}
                </View>
              ) : null}

              {suggestions.length > 0 ? (
                <View style={{ gap: spacing.sm }} testID="health-suggestions">
                  <Text style={hs.section}>WORTH TRYING</Text>
                  {suggestions.map((s, i) => (
                    <View key={i} style={hs.card} testID={`health-suggestion-${i}`}>
                      <Text style={hs.h}>{s.what}</Text>
                      {s.why ? <Text style={hs.body}>{s.why}</Text> : null}
                      {s.action ? <Text style={[hs.body, { color: colors.onSurface }]}><Text style={{ fontWeight: "700" }}>Try: </Text>{s.action}</Text> : null}
                      {s.review_in_days ? <Text style={hs.muted}>Check again in {s.review_in_days} {s.review_in_days === 1 ? "day" : "days"}</Text> : null}
                    </View>
                  ))}
                </View>
              ) : null}

              {dash ? (
                <View style={{ gap: spacing.sm }}>
                  <Text style={hs.section}>SIX AREAS</Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }} testID="health-domains">
                    {(dash.domains ?? []).map((d: any) => (
                      <Pressable key={d.domain} style={({ pressed }) => [hs.card, { width: "48.5%", minHeight: 116 }, pressed && { opacity: 0.85 }]} onPress={() => router.push(`/life/health/domain?key=${d.domain}` as any)} testID={`health-domain-${d.domain}`}>
                        <View style={[hs.dot, { backgroundColor: statusColour(d.colour) }]} testID={`health-domain-dot-${d.domain}-${d.colour}`} />
                        <Text style={[hs.h, { fontSize: 15 }]}>{d.label}</Text>
                        <Text style={{ fontSize: 12, fontStyle: "italic", color: colors.onSurfaceTertiary }}>{d.lens}</Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
              ) : null}

              {(dash?.risks ?? []).length > 0 ? (
                <View style={hs.card} testID="health-risks">
                  <Text style={hs.h}>Things to keep an eye on</Text>
                  {dash.risks.map((r: any, i: number) => (
                    <Text key={i} style={hs.body}>• {typeof r === "string" ? r : [r.what ?? r.label, r.why ?? r.note].filter(Boolean).join(" — ")}</Text>
                  ))}
                </View>
              ) : null}

              {missing.length > 0 ? (
                <View style={hs.card} testID="health-missing">
                  <Text style={hs.h}>Add when you can</Text>
                  <Text style={hs.body}>A fuller picture makes the suggestions better. No rush.</Text>
                  {shownMissing.map((m, i) => {
                    const daily = DAILY_METRICS.includes(m.metric);
                    return (
                      <View key={`${m.metric}-${i}`} style={{ flexDirection: "row", alignItems: "center", minHeight: 44, gap: spacing.sm }}>
                        <View style={{ flex: 1 }}>
                          <Text style={[hs.body, { color: colors.onSurface }]}>{m.label}</Text>
                          <Text style={hs.muted}>{m.domain}</Text>
                        </View>
                        {daily ? (
                          <Pressable style={[hs.chip, { minHeight: 36 }]} onPress={() => router.push("/life/health/daily" as any)} testID={`health-missing-add-${m.metric}`}>
                            <Text style={hs.chipText}>Add</Text>
                          </Pressable>
                        ) : <Text style={hs.muted}>At a check-up</Text>}
                      </View>
                    );
                  })}
                  {missing.length > 6 ? (
                    <Pressable onPress={() => setShowAllMissing(!showAllMissing)} style={{ minHeight: 40, justifyContent: "center" }} testID="health-missing-toggle">
                      <Text style={[hs.body, { fontWeight: "600", color: colors.brandPrimary }]}>{showAllMissing ? "Show fewer" : `Show all ${missing.length}`}</Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}

              {dash?.note ? <Text style={hs.muted} testID="health-note">{dash.note}</Text> : null}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
