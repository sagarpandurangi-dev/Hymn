import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, ApiError, StatementDetail, StatementLine, StatementProblem } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import StatementStatusBadge, { periodLabel } from "@/src/components/finance/StatementStatusBadge";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";
import { confirmAction } from "@/src/lib/confirm";

const lineNo = (l: StatementLine, i: number) => l.line ?? l.line_number ?? i + 1;
const problemLine = (p: StatementProblem) => p.line ?? p.line_number ?? null;
const problemText = (p: StatementProblem) => p.message ?? p.problem ?? p.reason ?? p.detail ?? "";
const amount = (v: StatementLine["debit"]) =>
  v === null || v === undefined || v === "" ? "" : formatMoney(String(v));

export default function StatementDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [doc, setDoc] = useState<StatementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      setDoc(await api.getStatement(String(id)));
      setError("");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, [id]);

  useEffect(() => {
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, [load]);

  const download = async () => {
    if (!doc || downloading) return;
    setDownloading(true);
    setError("");
    try {
      await api.downloadStatementFile(doc.id, doc.filename);
    } catch (e) {
      setError((e as ApiError).message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  const remove = async () => {
    if (!doc) return;
    const ok = await confirmAction("Delete statement?", `"${doc.filename}" and everything read from it will be permanently deleted.`, "Delete");
    if (!ok) return;
    setDeleting(true);
    setError("");
    try {
      await api.deleteStatement(doc.id);
      router.back();
    } catch (e) {
      setError((e as ApiError).message);
      setDeleting(false);
    }
  };

  const rawReasons = (doc?.verification as { reasons?: unknown } | null | undefined)?.reasons;
  const reasons = Array.isArray(rawReasons) ? rawReasons.filter((r): r is string => typeof r === "string" && r.trim() !== "") : [];
  const problems = doc?.verification?.problems ?? [];
  const flagged = new Set(problems.map(problemLine).filter((n): n is number => n !== null));
  const lines = doc?.lines ?? [];

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title={doc?.filename || "Statement"} subtitle={doc ? [doc.metadata?.institution, periodLabel(doc.metadata)].filter(Boolean).join(" · ") : undefined} />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {reasons.length > 0 ? (
            <FoldCard style={styles.reasons} testID="statement-reasons">
              {reasons.map((r, i) => (
                <Text key={i} style={styles.reasonText}>{r}</Text>
              ))}
            </FoldCard>
          ) : null}
          {doc ? (
            <View style={styles.statusRow}><StatementStatusBadge status={doc.status} /></View>
          ) : null}
          {error ? <Text style={styles.error} testID="statement-error">{error}</Text> : null}

          {problems.length > 0 ? (
            <FoldCard style={styles.problems} testID="statement-problems">
              <Text style={styles.problemsTitle}>Problems found</Text>
              {problems.map((p, i) => (
                <View key={i} style={styles.problemRow}>
                  <Text style={styles.problemLine}>{problemLine(p) !== null ? `Line ${problemLine(p)}` : "—"}</Text>
                  <Text style={styles.problemText}>{problemText(p)}</Text>
                </View>
              ))}
            </FoldCard>
          ) : null}

          {lines.length > 0 ? (
            <FoldCard style={styles.tableCard}>
              <ScrollView horizontal showsHorizontalScrollIndicator>
                <View>
                  <View style={[styles.tr, styles.th]}>
                    <Text style={[styles.cell, styles.cNo, styles.thText]}>#</Text>
                    <Text style={[styles.cell, styles.cDate, styles.thText]}>Date</Text>
                    <Text style={[styles.cell, styles.cDesc, styles.thText]}>Description</Text>
                    <Text style={[styles.cell, styles.cAmt, styles.thText]}>Debit</Text>
                    <Text style={[styles.cell, styles.cAmt, styles.thText]}>Credit</Text>
                    <Text style={[styles.cell, styles.cAmt, styles.thText]}>Balance</Text>
                  </View>
                  {lines.map((l, i) => {
                    const n = lineNo(l, i);
                    const bad = flagged.has(n);
                    return (
                      <View key={`${n}-${i}`} style={[styles.tr, bad && styles.trBad]} testID={`statement-line-${n}`}>
                        <Text style={[styles.cell, styles.cNo]}>{n}</Text>
                        <Text style={[styles.cell, styles.cDate]}>{l.date || ""}</Text>
                        <Text style={[styles.cell, styles.cDesc]} numberOfLines={2}>{l.description || ""}</Text>
                        <Text style={[styles.cell, styles.cAmt]}>{amount(l.debit)}</Text>
                        <Text style={[styles.cell, styles.cAmt]}>{amount(l.credit)}</Text>
                        <Text style={[styles.cell, styles.cAmt]}>{amount(l.balance)}</Text>
                      </View>
                    );
                  })}
                </View>
              </ScrollView>
            </FoldCard>
          ) : doc ? (
            <FoldCard><Text style={styles.empty}>No lines read yet.</Text></FoldCard>
          ) : null}

          {doc ? (
            <View style={styles.actions}>
              <Pressable style={[styles.primary, downloading && styles.disabled]} onPress={download} disabled={downloading} testID="statement-download-button">
                {downloading ? <ActivityIndicator color="#FBFBF6" /> : <Text style={styles.primaryText}>Download PDF</Text>}
              </Pressable>
              <Pressable style={[styles.danger, deleting && styles.disabled]} onPress={remove} disabled={deleting} testID="statement-delete-button">
                {deleting ? <ActivityIndicator color={financeColors.negative} /> : <Text style={styles.dangerText}>Delete</Text>}
              </Pressable>
            </View>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  statusRow: { flexDirection: "row" },
  error: { fontSize: 13, color: financeColors.negative },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  reasons: { padding: financeSpace.lg, gap: financeSpace.xs, backgroundColor: financeColors.pillWarnBg },
  reasonText: { fontSize: 13.5, lineHeight: 19, color: financeColors.pillWarnInk, fontWeight: "600" },
  problems: { padding: financeSpace.lg, gap: financeSpace.sm, backgroundColor: financeColors.pillWarnBg },
  problemsTitle: { fontSize: 14, fontWeight: "700", color: financeColors.pillWarnInk },
  problemRow: { flexDirection: "row", gap: financeSpace.md },
  problemLine: { width: 64, fontSize: 12.5, fontWeight: "700", color: financeColors.pillWarnInk },
  problemText: { flex: 1, fontSize: 13, color: financeColors.ink },
  tableCard: { paddingVertical: financeSpace.sm },
  tr: { flexDirection: "row", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: financeColors.divider, paddingVertical: financeSpace.sm },
  trBad: { backgroundColor: financeColors.pillWarnBg },
  th: { borderBottomColor: financeColors.cardBorder },
  thText: { fontWeight: "700", color: financeColors.inkMuted, fontSize: 11.5 },
  cell: { fontSize: 12.5, color: financeColors.ink, paddingHorizontal: financeSpace.sm },
  cNo: { width: 36, color: financeColors.inkMuted },
  cDate: { width: 92 },
  cDesc: { width: 200 },
  cAmt: { width: 96, textAlign: "right", fontVariant: ["tabular-nums"] },
  actions: { flexDirection: "row", gap: financeSpace.md, marginTop: financeSpace.md },
  primary: { flex: 1, backgroundColor: financeColors.ink, minHeight: 48, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center" },
  primaryText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700" },
  danger: { flex: 1, minHeight: 48, borderRadius: financeRadius.pill, borderWidth: 1, borderColor: financeColors.negative, alignItems: "center", justifyContent: "center" },
  dangerText: { color: financeColors.negative, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
});
