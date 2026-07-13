import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
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

const STEPS: { key: number; title: string; caption: string }[] = [
  { key: 0, title: "Reporting Currency", caption: "Your preferred display currency" },
  { key: 1, title: "Typical Week", caption: "Recurring weekly time blocks" },
  { key: 2, title: "Financial Position", caption: "Assets and liabilities" },
  { key: 3, title: "Monthly Money Commitments", caption: "Income, expenses, savings, debts" },
];

export default function PortfolioSetupScreen() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [status, setStatus] = useState<Status | null>(null);
  const [step, setStep] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const s = await api.getPortfolioSetupStatus();
      setStatus(s);
      // Resume at the first incomplete step: currency -> time -> money accounts -> money commitments.
      // If the wizard is re-entered after a partial pass we jump forward automatically.
      const resumeAt = (() => {
        if (!s.reporting_currency) return 0;
        if (!s.has_time_commitments) return 1;
        if (!s.has_financial_accounts) return 2;
        if (!s.has_monthly_money_commitments) return 3;
        return 3;
      })();
      setStep((prev) => (prev > resumeAt ? prev : resumeAt));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    (async () => { setLoading(true); await reload(); setLoading(false); })();
  }, [reload]);

  const applyCurrency = async (code: string) => {
    try {
      const updated = await api.updatePortfolioSetupStatus({ reporting_currency: code });
      setStatus(updated);
    } catch (e: any) {
      Alert.alert("Could not save currency", e?.message || "Please try again.");
    }
  };

  const finish = async () => {
    if (!status) return;
    setError(null);
    setSaving(true);
    try {
      await api.updatePortfolioSetupStatus({ completed: true });
      await refreshUser();
      router.replace("/(tabs)/today");
    } catch (e: any) {
      setError(e?.message || "Could not complete setup");
    } finally {
      setSaving(false);
    }
  };

  const canFinish = useMemo(() => {
    if (!status) return false;
    return (
      !!status.reporting_currency &&
      status.has_time_commitments &&
      status.has_financial_accounts &&
      status.has_monthly_money_commitments
    );
  }, [status]);

  if (loading || !status) {
    return (
      <SafeAreaView style={styles.safe}>
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.xxxl }} />
      </SafeAreaView>
    );
  }

  const canGoNext = (() => {
    if (step === 0) return !!status.reporting_currency;
    if (step === 1) return status.has_time_commitments;
    if (step === 2) return status.has_financial_accounts;
    return true;
  })();

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Text style={styles.title}>Portfolio Setup</Text>
        <Text style={styles.caption}>Step {step + 1} of {STEPS.length} · {STEPS[step].title}</Text>
      </View>

      <View style={styles.progressRow}>
        {STEPS.map((s) => (
          <View key={s.key} style={[styles.progressDot, s.key <= step && styles.progressDotDone]} />
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.stepCaption}>{STEPS[step].caption}</Text>

        {step === 0 && (
          <View style={{ gap: spacing.md }}>
            <Pressable
              onPress={() => setPickerOpen(true)}
              style={styles.currencyRow}
              testID="reporting-currency-select"
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.currencyLabel}>
                  {status.reporting_currency ? CURRENCY_LABEL(status.reporting_currency) : "Choose currency"}
                </Text>
                <Text style={styles.currencySub}>
                  Preferred display currency. Financial items keep their own original currency.
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
            </Pressable>
          </View>
        )}

        {step === 1 && (
          <WeeklyTimePortfolio onChanged={() => reload()} />
        )}
        {step === 2 && (
          <FinancialPositionPanel defaultCurrency={status.reporting_currency || "USD"} onChanged={() => reload()} />
        )}
        {step === 3 && (
          <MonthlyMoneyPanel defaultCurrency={status.reporting_currency || "USD"} onChanged={() => reload()} />
        )}

        {error && <Text style={styles.error}>{error}</Text>}
      </ScrollView>

      <View style={styles.footer}>
        {step > 0 && (
          <Pressable onPress={() => setStep(step - 1)} style={styles.secondary} testID="portfolio-setup-back">
            <Text style={styles.secondaryText}>Back</Text>
          </Pressable>
        )}
        {step < STEPS.length - 1 ? (
          <Pressable
            style={[styles.primary, !canGoNext && { opacity: 0.4 }]}
            disabled={!canGoNext}
            onPress={() => setStep(step + 1)}
            testID="portfolio-setup-next"
          >
            <Text style={styles.primaryText}>Continue</Text>
          </Pressable>
        ) : (
          <Pressable
            style={[styles.primary, (!canFinish || saving) && { opacity: 0.4 }]}
            disabled={!canFinish || saving}
            onPress={finish}
            testID="portfolio-setup-finish"
          >
            <Text style={styles.primaryText}>{saving ? "Saving…" : "Complete Setup"}</Text>
          </Pressable>
        )}
      </View>

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
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.xs },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: colors.onSurface, fontWeight: "700" },
  caption: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  progressRow: { flexDirection: "row", gap: spacing.xs, paddingHorizontal: spacing.xl, marginTop: spacing.md },
  progressDot: { flex: 1, height: 3, borderRadius: 2, backgroundColor: colors.border },
  progressDotDone: { backgroundColor: colors.brandPrimary },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xxxl, gap: spacing.md },
  stepCaption: { fontSize: 14, color: colors.onSurfaceSecondary },
  currencyRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg,
  },
  currencyLabel: { fontSize: 16, color: colors.onSurface, fontWeight: "600" },
  currencySub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
  footer: {
    flexDirection: "row", gap: spacing.md,
    paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  primary: { flex: 1, backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
  secondary: {
    paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
    borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  secondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.md },
});
