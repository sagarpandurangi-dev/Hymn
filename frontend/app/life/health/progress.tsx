import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

/** better = green, worse = amber, steady/changed = no colour (weight never praised or blamed). */
const WORD: Record<string, { label: string; color: string }> = {
  better: { label: "better", color: colors.success },
  worse: { label: "worse", color: colors.warning },
  steady: { label: "steady", color: colors.onSurfaceSecondary },
  changed: { label: "changed", color: colors.onSurfaceSecondary },
};
const fmt = (v: any) => {
  const n = Number(v);
  return v == null ? "—" : Number.isFinite(n) ? n.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : String(v);
};
const daysSince = (iso?: string | null) => {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Math.floor((Date.now() - new Date(y, m - 1, d).getTime()) / 86400000) + 1;
};

export default function ProgressScreen() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    api.getHealthProgress().then(setData).catch((e: ApiError) => setError(e.message || "Couldn't load your report."));
  }, []));

  const day = data ? Number(data.day ?? data.days ?? daysSince(data.start) ?? 0) : 0;
  const complete = !!(data?.complete ?? day >= 90);
  const lines: any[] = data?.lines ?? [];

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="progress-screen">
      <HealthHeader title="90-day report" testID="progress" />
      <ScrollView contentContainerStyle={hs.scroll}>
        {!data ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
          <>
            {data.rules_reviewed === false ? <DraftNote /> : null}
            {data.start && !complete ? (
              <View style={hs.card} testID="progress-day">
                <Text style={hs.h}>Day {Math.max(1, Math.min(day, 90))} of 90</Text>
                <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.surfaceTertiary, overflow: "hidden" }}>
                  <View style={{ width: `${Math.max(2, Math.min(100, (day / 90) * 100))}%`, height: 8, backgroundColor: colors.brandPrimary }} />
                </View>
              </View>
            ) : null}
            {lines.length === 0 ? (
              <Text style={hs.body} testID="progress-empty">{data.note || "Log for a few weeks to see how things change."}</Text>
            ) : (
              <View style={hs.card} testID="progress-lines">
                {lines.map((l, i) => {
                  const w = WORD[String(l.word ?? l.direction ?? l.trend ?? l.change ?? "")];
                  return (
                    <View key={l.metric ?? i} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, borderTopWidth: i ? 1 : 0, borderTopColor: colors.divider }} testID={`progress-line-${l.metric ?? i}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>{l.label}</Text>
                        <Text style={hs.muted}>{fmt(l.before)} → {fmt(l.after)}{l.unit ? ` ${l.unit}` : ""}</Text>
                      </View>
                      {w ? <Text style={{ fontSize: 13, fontWeight: "700", color: w.color }}>{w.label}</Text> : null}
                    </View>
                  );
                })}
              </View>
            )}
            {lines.length > 0 && data.note ? <Text style={hs.muted}>{data.note}</Text> : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
