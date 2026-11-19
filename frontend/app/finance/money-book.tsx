import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, ApiError, LedgerConversionPreview } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";
import { confirmAction } from "@/src/lib/confirm";

export default function MoneyBookScreen() {
  const [preview, setPreview] = useState<LedgerConversionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const load = useCallback(async () => {
    try {
      setPreview(await api.getLedgerConversionPreview());
      setError("");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useEffect(() => {
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, [load]);

  const canApprove = !!preview?.verification?.balances_match && !!preview?.verification?.spending_matches && !!preview?.fingerprint;

  const approve = async () => {
    if (!preview?.fingerprint || !canApprove || applying) return;
    const ok = await confirmAction(
      "Set up money book?",
      "Hymn will create your money book from the figures shown here.",
      "Approve",
    );
    if (!ok) return;
    setApplying(true);
    setError("");
    try {
      const res = await api.applyLedgerConversion(preview.fingerprint);
      const n = res?.entries_created ?? res?.created ?? (Array.isArray(res?.entries) ? res.entries.length : 0);
      setDone(`Done: ${n} entries created`);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setApplying(false);
    }
  };

  const summary = preview?.summary ?? [];
  const accounts = preview?.accounts ?? [];

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Money book" subtitle="Check, then approve" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={financeColors.ink} />}
        >
          {error ? <Text style={styles.error} testID="money-book-error">{error}</Text> : null}

          {preview?.already_converted ? (
            <FoldCard><Text style={styles.setUp} testID="money-book-set-up">Your money book is set up.</Text></FoldCard>
          ) : preview ? (
            <>
              {summary.length > 0 ? (
                <FoldCard style={styles.summary} testID="money-book-summary">
                  {summary.map((line, i) => {
                    const t = line.trim();
                    const tone = t.startsWith("✓") ? styles.ok : t.startsWith("✗") ? styles.bad : null;
                    return <Text key={i} style={[styles.summaryLine, tone]}>{line}</Text>;
                  })}
                </FoldCard>
              ) : null}

              {accounts.length > 0 ? (
                <FoldCard testID="money-book-accounts">
                  {accounts.map((a, i) => (
                    <View key={a.id ?? `${a.name}-${i}`}>
                      <FoldRow
                        first={i === 0}
                        label={a.name}
                        meta={`Opening ${a.currency} ${formatMoney(String(a.opening_balance))}`}
                        right={<FoldAmount currency={a.currency} value={formatMoney(String(a.ledger_balance_today))} />}
                      />
                    </View>
                  ))}
                </FoldCard>
              ) : null}

              {done ? (
                <Text style={[styles.summaryLine, styles.ok]} testID="money-book-done">{done}</Text>
              ) : (
                <Pressable
                  style={[styles.primary, (!canApprove || applying) && styles.disabled]}
                  onPress={approve}
                  disabled={!canApprove || applying}
                  testID="money-book-approve-button"
                >
                  {applying ? <ActivityIndicator color="#FBFBF6" /> : <Text style={styles.primaryText}>Approve and set up money book</Text>}
                </Pressable>
              )}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  error: { fontSize: 13, color: financeColors.negative },
  setUp: { fontSize: 15, color: financeColors.ink, padding: financeSpace.xl, textAlign: "center", fontWeight: "600" },
  summary: { padding: financeSpace.lg, gap: financeSpace.xs },
  summaryLine: { fontSize: 14, color: financeColors.ink, lineHeight: 20 },
  ok: { color: financeColors.positive, fontWeight: "600" },
  bad: { color: financeColors.negative, fontWeight: "600" },
  primary: { backgroundColor: financeColors.ink, minHeight: 48, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center", paddingHorizontal: financeSpace.lg, marginTop: financeSpace.md },
  primaryText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
});
