import { StyleSheet, Text, View, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { colors, fonts, spacing } from "@/src/lib/theme";

const TITLES: Record<string, string> = {
  health: "Health",
  family: "Family & Relationships",
  work: "Work",
};

/** Placeholder for Life areas that are not built yet. */
export default function LifeAreaPlaceholder() {
  const router = useRouter();
  const { area } = useLocalSearchParams<{ area: string }>();
  const title = TITLES[String(area)] ?? "Life";
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/life"))} hitSlop={12} style={styles.back} testID="life-area-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
      </View>
      <View style={styles.body}>
        <Text style={styles.title} testID="life-area-title">{title}</Text>
        <Text style={styles.soon} testID="life-area-coming-soon">Coming soon</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  back: { width: 44, height: 44, justifyContent: "center" },
  body: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.sm },
  title: { fontFamily: fonts.displayBold, fontSize: 32, fontWeight: "700", color: colors.onSurface },
  soon: { fontSize: 15, color: colors.onSurfaceSecondary },
});
