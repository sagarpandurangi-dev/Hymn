import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { formatMoney } from "@/src/lib/finance/format";

export default function LiabilitiesDrill() {
  const { currency } = useLocalSearchParams<{ currency: string }>();
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => { setLoading(true); try { setData(await api.getFinancePosition()); } catch { /* ignore */ } setLoading(false); })();
  }, []);

  const cur = data?.currencies?.find((c: any) => c.currency === currency);
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Total Liabilities" subtitle={currency} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.kpi}>{currency} {formatMoney(cur?.total_liabilities || "0")}</Text>
          <Text style={styles.section}>Contributing accounts</Text>
          {(cur?.accounts_liability || []).map((a: any) => (
            <View key={a.id} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowLabel}>{a.name}</Text>
                <Text style={styles.rowMeta}>{a.account_type}</Text>
              </View>
              <Text style={styles.rowValue}>{currency} {formatMoney(a.current_value)}</Text>
            </View>
          ))}
          {(!cur?.accounts_liability || cur.accounts_liability.length === 0) && <Text style={styles.empty}>No liabilities in {currency}.</Text>}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  kpi: { fontSize: 28, fontWeight: "700", color: colors.onSurface },
  section: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, letterSpacing: 0.5 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: spacing.md },
  rowLabel: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.md },
});
