import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs, niceDay } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

const sourceName = (s: any) => s?.label ?? s?.name ?? String(s?.source_app ?? s?.app ?? "").replace(/_/g, " ");
const sourceId = (s: any) => String(s?.source_app ?? s?.app ?? s?.id ?? "");

/** Two questions: disconnect, then keep or delete its readings. */
const askDisconnect = (name: string, run: (deleteData: boolean) => void) => {
  const body = `Stop syncing from ${name}? You can keep the readings it already sent, or delete them.`;
  if (Platform.OS === "web") {
    if (!window.confirm(body)) return;
    run(window.confirm("Also delete the readings it sent? Press Cancel to keep them."));
    return;
  }
  Alert.alert("Disconnect", body, [
    { text: "Cancel", style: "cancel" },
    { text: "Keep readings", onPress: () => run(false) },
    { text: "Delete readings", style: "destructive", onPress: () => run(true) },
  ]);
};

export default function WatchScreen() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.getHealthSync());
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load this.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const disconnect = (s: any) => askDisconnect(sourceName(s), async (deleteData) => {
    setBusy(sourceId(s));
    try {
      await api.disconnectHealthSource(sourceId(s), deleteData);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't disconnect. Try again.");
    } finally {
      setBusy("");
    }
  });

  const hubs: any[] = data?.hubs ?? [];
  const sources: any[] = data?.sources ?? [];

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="watch-screen">
      <HealthHeader title="Connect a watch" testID="watch" />
      <ScrollView contentContainerStyle={hs.scroll}>
        {!data ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
          <>
            {data.note ? <Text style={hs.body}>{data.note}</Text> : null}
            {error ? <Text style={hs.error}>{error}</Text> : null}
            {hubs.map((h, i) => (
              <View key={i} style={hs.card} testID={`watch-hub-${i}`}>
                <Text style={hs.muted}>{h.phone}</Text>
                <Text style={hs.h}>{h.hub}</Text>
                <Text style={hs.body}>{h.works_with}</Text>
                {h.hub !== "No watch" ? (
                  <>
                    <Pressable style={[hs.secondary, { opacity: 0.45 }]} disabled accessibilityState={{ disabled: true }} testID={`watch-connect-${i}`}>
                      <Ionicons name="link-outline" size={18} color={colors.onSurface} />
                      <Text style={hs.secondaryText}>Connect</Text>
                    </Pressable>
                    <Text style={[hs.muted, { textAlign: "center" }]}>Coming in the next app update</Text>
                  </>
                ) : null}
              </View>
            ))}

            <View style={{ gap: spacing.sm }}>
              <Text style={hs.section}>CONNECTED</Text>
              {sources.length === 0 ? <Text style={hs.muted} testID="watch-no-sources">Nothing connected yet.</Text> : sources.map((s) => (
                <View key={sourceId(s)} style={[hs.card, { flexDirection: "row", alignItems: "center", gap: spacing.sm }]} testID={`watch-source-${sourceId(s)}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={[hs.h, { fontSize: 15 }]}>{sourceName(s)}</Text>
                    <Text style={hs.muted}>{s.last_sync ? `Last sync ${niceDay(s.last_sync)}` : "Not synced yet"}</Text>
                  </View>
                  <Pressable style={[hs.chip, { minHeight: 36 }]} onPress={() => disconnect(s)} disabled={busy === sourceId(s)} testID={`watch-disconnect-${sourceId(s)}`}>
                    {busy === sourceId(s) ? <ActivityIndicator size="small" color={colors.onSurface} /> : <Text style={hs.chipText}>Disconnect</Text>}
                  </Pressable>
                </View>
              ))}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
