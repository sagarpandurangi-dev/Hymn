import { useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api, AccountSetup } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";

const SNOOZE_KEY = "hymn.setupCard.snoozedUntil";
const SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;

// Server screen keys → app routes.
const SCREEN_ROUTES: Record<string, string> = {
  settings: "/nudges",
  "portfolio/setup": "/portfolio",
  work: "/life/work",
  people: "/life/family",
  "plan-chat": "/(tabs)/planning-space",
  health: "/life/health",
  "inbox/dump": "/inbox/dump",
};

/** "Finish setting up — N of M done" card for Today. Hidden when complete or snoozed. */
export default function SetupProgressCard() {
  const router = useRouter();
  const [setup, setSetup] = useState<AccountSetup | null>(null);
  const [hidden, setHidden] = useState(true);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        const until = Number((await AsyncStorage.getItem(SNOOZE_KEY).catch(() => null)) || 0);
        if (until > Date.now()) { if (alive) setHidden(true); return; }
        try {
          const s = await api.getAccountSetup();
          if (alive) { setSetup(s); setHidden(Boolean(s.complete) || !s.next); }
        } catch {
          if (alive) setHidden(true);
        }
      })();
      return () => { alive = false; };
    }, []),
  );

  if (hidden || !setup?.next) return null;
  const next = setup.next;
  const route = SCREEN_ROUTES[next.screen];

  const notNow = async () => {
    setHidden(true);
    await AsyncStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS)).catch(() => undefined);
  };

  return (
    <View style={styles.card} testID="setup-progress-card">
      <Text style={styles.title} testID="setup-progress-count">Finish setting up — {setup.done} of {setup.of} done</Text>
      <Text style={styles.next}>{next.title}</Text>
      {next.why ? <Text style={styles.why}>{next.why}</Text> : null}
      <View style={styles.row}>
        {route ? (
          <Pressable onPress={() => router.push(route as any)} style={styles.primary} testID="setup-progress-open">
            <Text style={styles.primaryText}>Do it now</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={notNow} style={styles.secondary} testID="setup-progress-not-now">
          <Text style={styles.secondaryText}>Not now</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.xs },
  title: { fontSize: 12, fontWeight: "700", letterSpacing: 0.4, color: colors.onBrandTertiary },
  next: { fontSize: 16, fontWeight: "600", color: colors.onSurface, marginTop: spacing.xs },
  why: { fontSize: 13, color: colors.onSurfaceSecondary },
  row: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm, alignItems: "center" },
  primary: { minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.onSurface, justifyContent: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "600" },
  secondary: { minHeight: 44, paddingHorizontal: spacing.md, justifyContent: "center" },
  secondaryText: { color: colors.onSurfaceSecondary, fontSize: 14 },
});
