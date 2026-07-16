import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { colors, fonts, spacing } from "@/src/lib/theme";

export default function FinanceHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  const router = useRouter();
  return (
    <SafeAreaView edges={["top"]} style={styles.safe}>
      <View style={styles.row}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="finance-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          {subtitle ? <Text style={styles.sub}>{subtitle}</Text> : null}
        </View>
        {right ? <View>{right}</View> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: colors.surface },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.xl, paddingTop: spacing.sm, paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 20, color: colors.onSurface, fontWeight: "700" },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2, letterSpacing: 0.4 },
});
