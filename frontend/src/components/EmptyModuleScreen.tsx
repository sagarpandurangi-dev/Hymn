import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, spacing } from "@/src/lib/theme";

type Props = {
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  message: string;
  testID: string;
};

export default function EmptyModuleScreen({ title, icon, message, testID }: Props) {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID={testID}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>{title}</Text>
        <View style={{ width: 22 }} />
      </View>
      <View style={styles.wrap}>
        <Ionicons name={icon} size={44} color={colors.onSurfaceTertiary} />
        <Text style={styles.emptyTitle}>{title}</Text>
        <Text style={styles.text}>{message}</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 24, color: colors.onSurface, fontWeight: "700", marginTop: spacing.md },
  text: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
});
