import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import { CURRENCY_LABEL } from "@/src/lib/portfolio/constants";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";
import {
  FinancialPositionPanel,
  MonthlyMoneyPanel,
  WeeklyTimePortfolio,
} from "@/src/components/portfolio/PortfolioPanels";

type Status = {
  completed: boolean;
  completed_at: string | null;
  reporting_currency: string | null;
  has_time_commitments: boolean;
  has_financial_accounts: boolean;
  has_monthly_money_commitments: boolean;
};

export default function PortfolioScreen() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);

  const reload = useCallback(async () => {
    try { setStatus(await api.getPortfolioSetupStatus()); } catch { /* ignore */ }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await reload(); setLoading(false); })(); }, [reload]);

  const applyCurrency = async (code: string) => {
    try {
      const s = await api.updatePortfolioSetupStatus({ reporting_currency: code });
      setStatus(s);
    } catch (e: any) {
      Alert.alert("Could not save currency", e?.message || "Please try again.");
    }
  };

  if (loading || !status) {
    return (
      <SafeAreaView style={styles.safe}>
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.xxxl }} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="portfolio-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Portfolio</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.sectionHead}>Reporting Currency</Text>
        <Pressable onPress={() => setPickerOpen(true)} style={styles.currencyRow} testID="portfolio-currency">
          <Text style={styles.currencyLabel}>
            {status.reporting_currency ? CURRENCY_LABEL(status.reporting_currency) : "Choose currency"}
          </Text>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>

        <Text style={styles.sectionHead}>Weekly Time Portfolio</Text>
        <WeeklyTimePortfolio />

        <Text style={styles.sectionHead}>Financial Position</Text>
        <FinancialPositionPanel defaultCurrency={status.reporting_currency || "USD"} />

        <Text style={styles.sectionHead}>Monthly Money Commitments</Text>
        <MonthlyMoneyPanel defaultCurrency={status.reporting_currency || "USD"} />
      </ScrollView>

      <CurrencyPickerModal
        visible={pickerOpen}
        selected={status.reporting_currency}
        onSelect={applyCurrency}
        onClose={() => setPickerOpen(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
  },
  title: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  sectionHead: {
    marginTop: spacing.xl,
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    letterSpacing: 1.2,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  currencyRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg,
  },
  currencyLabel: { flex: 1, fontSize: 15, color: colors.onSurface, fontWeight: "600" },
});
