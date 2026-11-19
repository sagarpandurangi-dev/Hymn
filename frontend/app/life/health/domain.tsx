import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import { HealthHeader, hs, statusColour, statusText } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso?: string) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
};
const val = (v: any) => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : String(v);
};
const source = (s?: string) => (s === "you" ? "You added this" : s ? `From ${s.replace(/_/g, " ")}` : "");

export default function HealthDomainScreen() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const [dash, setDash] = useState<any>(null);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    api.getHealthDashboard().then(setDash).catch((e: ApiError) => setError(e.message || "Couldn't load this."));
  }, []));

  const d = (dash?.domains ?? []).find((x: any) => x.domain === key);
  const inds: any[] = d?.indicators ?? [];

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-domain-screen">
      <HealthHeader title={d?.label ?? "Health"} testID="health-domain" />
      <ScrollView contentContainerStyle={hs.scroll}>
        {!dash ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : !d ? (
          <Text style={hs.body}>This area isn&apos;t available.</Text>
        ) : (
          <>
            <Text style={{ fontSize: 14, fontStyle: "italic", color: colors.onSurfaceTertiary, marginTop: -spacing.sm }}>{d.lens}</Text>
            {dash.rules_reviewed === false ? <DraftNote /> : null}
            {inds.map((i) => {
              const has = i.value != null && i.status !== "missing" && i.status !== "not_measured";
              return (
                <View key={i.metric} style={hs.card} testID={`health-indicator-${i.metric}`}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                    <View style={[hs.dot, { backgroundColor: statusColour(i.status) }]} />
                    <Text style={[hs.h, { flex: 1, fontSize: 15 }]}>{i.label}</Text>
                    {has ? <Text style={[hs.h, { fontSize: 15 }]}>{val(i.value)}{i.unit ? <Text style={hs.muted}> {i.unit}</Text> : null}</Text> : null}
                  </View>
                  <Text style={[hs.muted, i.status === "green" && { color: colors.success }]} testID={`health-indicator-status-${i.metric}`}>{statusText(i.status)}{i.why && has ? ` · ${i.why}` : ""}</Text>
                  {has ? (
                    <Text style={hs.muted}>{[day(i.taken_on), source(i.source), i.based_on].filter(Boolean).join(" · ")}</Text>
                  ) : null}
                </View>
              );
            })}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
