import { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { entryText, reportMoney } from "@/src/components/finance/ReportBits";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

/** Entries behind one Income & Expenditure category for a date range. */
export default function ReportEntries() {
  const { category, label, start, end, currency } = useLocalSearchParams<{ category: string; label?: string; start: string; end: string; currency?: string }>();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    (async () => {
      setError("");
      try {
        const res: any = await api.getReportEntries(String(category), String(start), String(end));
        setRows(Array.isArray(res) ? res : res?.entries ?? res?.items ?? []);
      } catch (e) {
        setError((e as ApiError).message);
      } finally {
        setLoading(false);
      }
    })();
  }, [category, start, end]));

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={label || category || "Entries"} subtitle={start && end ? `${dateLabel(start)} – ${dateLabel(end)}` : undefined} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <FlatList
          contentContainerStyle={styles.scroll}
          data={rows}
          keyExtractor={(r, i) => String(r.id ?? i)}
          ListHeaderComponent={error ? <Text style={styles.error} testID="entries-error">{error}</Text> : null}
          ListEmptyComponent={!error ? <Text style={styles.empty} testID="entries-empty">No entries in this period.</Text> : null}
          renderItem={({ item, index }) => (
            <FoldCard style={{ marginBottom: 1 }}>
              <FoldRow
                first={index === 0}
                label={entryText(item)}
                meta={item.date ? dateLabel(item.date) : undefined}
                right={<FoldAmount value={reportMoney(item.currency || currency, item.amount)} />}
                testID={`entry-${index}`}
              />
            </FoldCard>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.lg, paddingBottom: financeSpace.xxxl * 2 },
  empty: { fontSize: 13, color: financeColors.inkMuted, textAlign: "center", marginTop: financeSpace.xl },
  error: { fontSize: 13, color: financeColors.negative, marginBottom: financeSpace.md },
});
