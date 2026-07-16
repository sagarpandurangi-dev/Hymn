import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";

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
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Audit trail" subtitle={`${recordType} · ${recordId?.slice(0, 8) || ""}…`} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 && <Text style={styles.empty}>No history recorded for this record.</Text>}
          {rows.map((e) => (
            <View key={e.id} style={styles.row}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={styles.action}>{e.action}</Text>
                <Text style={styles.source}>{e.source}</Text>
              </View>
              <Text style={styles.time}>{e.timestamp?.replace("T", " ").slice(0, 19)} UTC</Text>
              {e.previous_value ? <Text style={styles.prev}>Before: {JSON.stringify(e.previous_value)}</Text> : null}
              {e.new_value ? <Text style={styles.next}>After: {JSON.stringify(e.new_value)}</Text> : null}
              {(e.related_checkin_id || e.related_task_id || e.related_event_id) ? (
                <Text style={styles.related}>
                  {e.related_checkin_id ? `checkin ${e.related_checkin_id.slice(0, 8)}… ` : ""}
                  {e.related_task_id ? `task ${e.related_task_id.slice(0, 8)}… ` : ""}
                  {e.related_event_id ? `event ${e.related_event_id.slice(0, 8)}… ` : ""}
                </Text>
              ) : null}
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.xl, textAlign: "center" },
  row: { padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, gap: 4 },
  action: { fontSize: 13, color: colors.onSurface, fontWeight: "700" },
  source: { fontSize: 11, color: colors.onSurfaceSecondary },
  time: { fontSize: 11, color: colors.onSurfaceSecondary },
  prev: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4, fontFamily: "monospace" },
  next: { fontSize: 11, color: colors.onSurface, fontFamily: "monospace" },
  related: { fontSize: 10, color: colors.brandPrimary, marginTop: 4 },
});
