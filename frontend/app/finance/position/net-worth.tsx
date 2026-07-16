import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney } from "@/src/lib/finance/format";

export default function NetWorthDrill() {
  const router = useRouter();
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinancePosition()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Net Worth" subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.kpi}>{currency} {formatMoney(cur?.net_worth || "0")}</Text>
          <Text style={styles.formula}>Net Worth = Total Assets − Total Liabilities</Text>
          <Pressable style={styles.row} onPress={() => router.push(`/finance/position/assets?currency=${currency}`)} testID="nw-assets-drill">
            <View style={{ flex: 1 }}><Text style={styles.rowLabel}>Total Assets</Text><Text style={styles.rowMeta}>Tap for breakdown</Text></View>
            <Text style={styles.rowValue}>{currency} {formatMoney(cur?.total_assets || "0")}</Text>
          </Pressable>
          <Pressable style={styles.row} onPress={() => router.push(`/finance/position/liabilities?currency=${currency}`)} testID="nw-liabilities-drill">
            <View style={{ flex: 1 }}><Text style={styles.rowLabel}>Total Liabilities</Text><Text style={styles.rowMeta}>Tap for breakdown</Text></View>
            <Text style={styles.rowValue}>{currency} {formatMoney(cur?.total_liabilities || "0")}</Text>
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  kpi: { fontSize: 32, fontWeight: "700", color: colors.onSurface },
  formula: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic" },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowLabel: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowValue: { fontSize: 15, color: colors.onSurface, fontWeight: "700" },
});
