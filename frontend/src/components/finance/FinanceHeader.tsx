import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { financeColors, financeSpace, financeType } from "@/src/lib/finance/theme";

export default function FinanceHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  const router = useRouter();
  return (
    <SafeAreaView edges={["top"]} style={styles.safe}>
      <View style={styles.row}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="finance-back" style={styles.back}>
          <Ionicons name="chevron-back" size={20} color={financeColors.ink} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
          {subtitle ? <Text style={styles.sub} numberOfLines={1}>{subtitle}</Text> : null}
        </View>
        {right ? <View>{right}</View> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: financeColors.page },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: financeSpace.md,
    paddingHorizontal: financeSpace.xl,
    paddingTop: financeSpace.xs,
    paddingBottom: financeSpace.md,
  },
  back: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    marginLeft: -6,
  },
  title: {
    ...financeType.screenTitle,
    fontSize: 22,
  } as any,
  sub: {
    fontSize: 12,
    color: financeColors.inkMuted,
    marginTop: 2,
    letterSpacing: 0.3,
  },
});
