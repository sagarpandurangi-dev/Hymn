import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, spacing } from "@/src/lib/theme";

export default function FinanceScreen() {
  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="finance-screen">
      <View style={styles.wrap}>
        <Ionicons name="wallet-outline" size={44} color={colors.onSurfaceTertiary} />
        <Text style={styles.title}>Finance</Text>
        <Text style={styles.text}>Financial tracking is quiet right now.</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.md },
  text: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
});
