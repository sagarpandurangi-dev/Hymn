import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

export default function AuditTrail() {
  const { recordType, recordId } = useLocalSearchParams<{ recordType: string; recordId: string }>();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const t = await api.getFinancialAudit(recordType, recordId);
        setRows(t?.entries || []);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, [recordType, recordId]);

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Audit trail" subtitle={`${recordType} · ${recordId?.slice(0, 8) || ""}…`} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No history recorded for this record.</Text></FoldCard>
          ) : (
            rows.map((e, idx) => (
              <FoldCard key={e.id} style={styles.card}>
                <View style={styles.head}>
                  <Text style={styles.action}>{e.action}</Text>
                  <Text style={styles.source}>{e.source}</Text>
                </View>
                <Text style={styles.time}>{e.timestamp?.replace("T", " ").slice(0, 19)} UTC</Text>
                {e.previous_value ? <Text style={styles.prev}>Before · {JSON.stringify(e.previous_value)}</Text> : null}
                {e.new_value ? <Text style={styles.next}>After · {JSON.stringify(e.new_value)}</Text> : null}
                {(e.related_checkin_id || e.related_task_id || e.related_event_id) ? (
                  <Text style={styles.related}>
                    {e.related_checkin_id ? `checkin ${e.related_checkin_id.slice(0, 8)}… ` : ""}
                    {e.related_task_id ? `task ${e.related_task_id.slice(0, 8)}… ` : ""}
                    {e.related_event_id ? `event ${e.related_event_id.slice(0, 8)}… ` : ""}
                  </Text>
                ) : null}
              </FoldCard>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.sm, paddingBottom: financeSpace.xxxl },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  card: { padding: financeSpace.md, gap: 4 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  action: { fontSize: 13, color: financeColors.ink, fontWeight: "700" },
  source: { fontSize: 10.5, color: financeColors.inkMuted, letterSpacing: 0.6, textTransform: "uppercase" },
  time: { fontSize: 11, color: financeColors.inkMuted, letterSpacing: 0.3 },
  prev: { fontSize: 11, color: financeColors.inkMuted, marginTop: 4, fontFamily: "monospace" },
  next: { fontSize: 11, color: financeColors.ink, fontFamily: "monospace" },
  related: { fontSize: 10.5, color: financeColors.accent, marginTop: 4, letterSpacing: 0.3 },
});
