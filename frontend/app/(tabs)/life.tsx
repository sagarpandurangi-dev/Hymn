import { useCallback, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export const FOCUS_AREAS_KEY = "hymn.focusAreas";

type Area = {
  key: string;
  name: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  path: string;
  line: string; // short status line — filled in later
};

const AREAS: Area[] = [
  { key: "health", name: "Health", icon: "heart-outline", path: "/life/health", line: "" },
  { key: "family", name: "Family & Relationships", icon: "people-outline", path: "/life/family", line: "" },
  { key: "learning", name: "Learning", icon: "school-outline", path: "/(tabs)/knowledge", line: "" },
  { key: "work", name: "Work", icon: "briefcase-outline", path: "/life/work", line: "" },
  { key: "plans", name: "Plans", icon: "map-outline", path: "/(tabs)/planning-space", line: "" },
];

/** Saved focus areas come first (in their saved order), then the rest in default order. */
function orderAreas(focus: string[]): Area[] {
  const first = [...new Set(focus)].map((k) => AREAS.find((a) => a.key === k)).filter((a): a is Area => Boolean(a));
  return [...first, ...AREAS.filter((a) => !first.includes(a))];
}

export default function LifeScreen() {
  const router = useRouter();
  const [areas, setAreas] = useState<Area[]>(AREAS);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      AsyncStorage.getItem(FOCUS_AREAS_KEY)
        .then((raw) => {
          const parsed = raw ? JSON.parse(raw) : [];
          if (alive) setAreas(orderAreas(Array.isArray(parsed) ? parsed.map(String) : []));
        })
        .catch(() => { if (alive) setAreas(AREAS); });
      return () => { alive = false; };
    }, []),
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.header}>Life</Text>
        <View style={styles.list}>
          {areas.map((a) => (
            <Pressable
              key={a.key}
              onPress={() => router.push(a.path as any)}
              style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
              testID={`life-card-${a.key}`}
              accessibilityRole="button"
            >
              <View style={styles.iconWrap}>
                <Ionicons name={a.icon} size={22} color={colors.brandPrimary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{a.name}</Text>
                {a.line ? <Text style={styles.line} numberOfLines={1}>{a.line}</Text> : null}
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xxxl * 2 },
  header: { fontFamily: fonts.displayBold, fontSize: 36, fontWeight: "700", color: colors.onSurface, marginBottom: spacing.xl },
  list: { gap: spacing.md },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 72,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg,
  },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  name: { fontSize: 16, fontWeight: "600", color: colors.onSurface },
  line: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
});
