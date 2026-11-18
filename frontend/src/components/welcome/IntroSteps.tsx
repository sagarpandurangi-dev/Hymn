import { useEffect, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";

import WelcomeShell, { StepNav } from "./WelcomeShell";
import Chips from "./Chips";
import { api, ApiError } from "@/src/lib/api";
import { FOCUS_AREAS_KEY } from "@/src/lib/welcome";
import { formStyles as fs } from "@/src/lib/formStyles";
import { colors, radius, spacing } from "@/src/lib/theme";

const AREAS: { value: string; label: string; line: string; icon: React.ComponentProps<typeof Ionicons>["name"] }[] = [
  { value: "money", label: "Money", line: "Know what you can really spend.", icon: "wallet-outline" },
  { value: "health", label: "Health", line: "Small daily care that adds up.", icon: "heart-outline" },
  { value: "family", label: "Family & Relationships", line: "Never miss the people who matter.", icon: "people-outline" },
  { value: "learning", label: "Learning", line: "Keep growing, a little at a time.", icon: "school-outline" },
  { value: "work", label: "Work", line: "Your real hours, not guesses.", icon: "briefcase-outline" },
];

export function PromiseStep({ nav }: { nav: StepNav }) {
  return (
    <WelcomeShell nav={nav} title="Hymn helps you follow through on your life." primaryLabel="Let's start" onPrimary={nav.next}>
      <View style={{ gap: spacing.lg }}>
        {AREAS.map((a) => (
          <View key={a.value} style={styles.areaRow} testID={`welcome-area-${a.value}`}>
            <Ionicons name={a.icon} size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.areaName}>{a.label}</Text>
              <Text style={styles.areaLine}>{a.line}</Text>
            </View>
          </View>
        ))}
      </View>
    </WelcomeShell>
  );
}

export function FocusStep({ nav }: { nav: StepNav }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [hint, setHint] = useState("");

  useEffect(() => {
    AsyncStorage.getItem(FOCUS_AREAS_KEY).then((raw) => {
      try {
        const v = raw ? JSON.parse(raw) : [];
        if (Array.isArray(v)) setPicked(v.map(String).filter((k) => AREAS.some((a) => a.value === k)).slice(0, 3));
      } catch { /* ignore */ }
    }).catch(() => undefined);
  }, []);

  const toggle = (v: string) => {
    setHint("");
    if (picked.includes(v)) setPicked(picked.filter((x) => x !== v));
    else if (picked.length >= 3) setHint("Pick up to 3.");
    else setPicked([...picked, v]);
  };

  const save = async () => {
    await AsyncStorage.setItem(FOCUS_AREAS_KEY, JSON.stringify(picked)).catch(() => undefined);
    nav.next();
  };

  return (
    <WelcomeShell nav={nav} title="What matters most right now?" subtitle="Pick up to 3. Hymn will put these first." primaryLabel="Continue" onPrimary={save} primaryDisabled={picked.length === 0}>
      <Chips options={AREAS} selected={picked} onToggle={toggle} testID="welcome-focus" />
      {hint ? <Text style={styles.hint} testID="welcome-focus-hint">{hint}</Text> : null}
    </WelcomeShell>
  );
}

const FALLBACK_ZONES = [
  "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Asia/Shanghai", "Asia/Karachi", "Asia/Dhaka", "Asia/Kathmandu",
  "Europe/London", "Europe/Paris", "Europe/Berlin", "Africa/Nairobi", "Africa/Johannesburg", "Australia/Sydney",
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Toronto", "America/Sao_Paulo", "UTC",
];

// Old ↔ new zone names, so either spelling finds the zone.
const ZONE_ALIASES: Record<string, string> = {
  kolkata: "calcutta", calcutta: "kolkata", kathmandu: "katmandu", kyiv: "kiev", kiev: "kyiv",
  ho_chi_minh: "saigon", saigon: "ho_chi_minh", india: "kolkata", bombay: "kolkata", mumbai: "kolkata", delhi: "kolkata",
};

export function TimezoneStep({ nav }: { nav: StepNav }) {
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [zone, setZone] = useState(detected);
  const [changing, setChanging] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const zones = useMemo(() => {
    const listed: string[] = (Intl as any).supportedValuesOf?.("timeZone") ?? [];
    // Some browsers only list old names (e.g. Asia/Calcutta), so always include the common modern ones.
    const all = Array.from(new Set([...FALLBACK_ZONES, ...listed]));
    const q = query.trim().toLowerCase().replace(/\s+/g, "_");
    if (!q) return all.slice(0, 30);
    const terms = [q, ...(ZONE_ALIASES[q] ? [ZONE_ALIASES[q]] : [])];
    return all.filter((z) => terms.some((t) => z.toLowerCase().includes(t))).slice(0, 30);
  }, [query]);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api.updateNudgeSettings({ timezone: zone });
      nav.next();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save your time zone.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <WelcomeShell nav={nav} title="Your time zone" subtitle="So reminders arrive at the right time." primaryLabel="Continue" onPrimary={save} busy={busy} error={error}>
      <View style={styles.zoneRow}>
        <Text style={styles.zoneText} testID="welcome-timezone-value">{zone.replace(/_/g, " ")}</Text>
        <Pressable onPress={() => setChanging(!changing)} hitSlop={12} style={styles.changeBtn} testID="welcome-timezone-change">
          <Text style={styles.changeText}>{changing ? "Done" : "Change"}</Text>
        </Pressable>
      </View>
      {changing ? (
        <View style={{ marginTop: spacing.md, gap: spacing.sm }}>
          <TextInput
            style={fs.input}
            value={query}
            onChangeText={setQuery}
            placeholder="Search a city, e.g. Kolkata"
            placeholderTextColor={colors.onSurfaceTertiary}
            autoCorrect={false}
            testID="welcome-timezone-search"
          />
          {zones.map((z) => (
            <Pressable key={z} onPress={() => { setZone(z); setChanging(false); }} style={styles.zoneOption} testID={`welcome-timezone-option-${z}`}>
              <Text style={[styles.zoneOptionText, z === zone && { fontWeight: "700" }]}>{z.replace(/_/g, " ")}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </WelcomeShell>
  );
}

const styles = StyleSheet.create({
  areaRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  areaName: { fontSize: 16, fontWeight: "600", color: colors.onSurface },
  areaLine: { fontSize: 14, color: colors.onSurfaceSecondary, marginTop: 2 },
  hint: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.md },
  zoneRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingLeft: spacing.lg, paddingRight: spacing.sm, minHeight: 56 },
  zoneText: { flex: 1, fontSize: 17, fontWeight: "600", color: colors.onSurface },
  changeBtn: { minHeight: 44, minWidth: 64, alignItems: "center", justifyContent: "center" },
  changeText: { fontSize: 15, fontWeight: "600", color: colors.brandPrimary },
  zoneOption: { minHeight: 44, justifyContent: "center", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  zoneOptionText: { fontSize: 15, color: colors.onSurface },
});
