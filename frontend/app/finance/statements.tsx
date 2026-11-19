import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import { api, ApiError, Statement } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, foldPageStyle } from "@/src/components/finance/foldUi";
import StatementStatusBadge, { periodLabel } from "@/src/components/finance/StatementStatusBadge";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { uploadForm, UploadFile } from "@/src/utils/upload";
import { confirmAction } from "@/src/lib/confirm";

const POLL_MS = 5000;

export default function StatementsScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<Statement[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<UploadFile | null>(null);
  const [password, setPassword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [deletingAll, setDeletingAll] = useState(false);
  const focused = useRef(false);

  const load = useCallback(async () => {
    try {
      const list = await api.listStatements();
      setRows(Array.isArray(list) ? list : []);
      setError("");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      focused.current = true;
      (async () => {
        setLoading(true);
        await load();
        setLoading(false);
      })();
      return () => { focused.current = false; };
    }, [load]),
  );

  // Refresh every 5 seconds while any statement is still being read.
  const anyReading = rows.some((r) => r.status === "reading");
  useEffect(() => {
    if (!anyReading) return;
    const t = setInterval(() => { if (focused.current) void load(); }, POLL_MS);
    return () => clearInterval(t);
  }, [anyReading, load]);

  const pick = async () => {
    setUploadError("");
    const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true, multiple: false });
    if (res.canceled || !res.assets?.[0]) return;
    const a = res.assets[0];
    setPassword("");
    setPicked({ uri: a.uri, name: a.name || "statement.pdf", mimeType: a.mimeType || "application/pdf" });
  };

  const upload = async () => {
    if (!picked || uploading) return;
    setUploading(true);
    setUploadError("");
    try {
      const form = await uploadForm("file", picked, { password: password.trim() ? password : undefined });
      await api.uploadStatement(form);
      setPicked(null);
      setPassword("");
      await load();
    } catch (e) {
      setUploadError((e as ApiError).message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const deleteAll = async () => {
    const ok = await confirmAction(
      "Delete all documents?",
      "This permanently deletes every statement you've uploaded and everything read from them.",
      "Delete all",
    );
    if (!ok) return;
    setDeletingAll(true);
    setError("");
    try {
      await api.deleteAllStatements();
      await load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setDeletingAll(false);
    }
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Statements" subtitle="Bank statements, checked line by line" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={financeColors.ink} />}
        >
          <Pressable style={styles.primary} onPress={pick} testID="statements-upload-button">
            <Text style={styles.primaryText}>Upload statement</Text>
          </Pressable>

          {error ? <Text style={styles.error} testID="statements-error">{error}</Text> : null}

          {rows.length === 0 && !error ? (
            <FoldCard><Text style={styles.empty}>No statements yet.</Text></FoldCard>
          ) : null}
          {rows.map((r) => (
            <Pressable key={r.id} onPress={() => router.push(`/finance/statements/${r.id}`)} testID={`statement-row-${r.id}`}>
              <FoldCard style={styles.card}>
                <View style={styles.head}>
                  <Text style={styles.title} numberOfLines={1}>{r.filename}</Text>
                  <StatementStatusBadge status={r.status} />
                </View>
                {r.metadata?.institution ? <Text style={styles.meta}>{r.metadata.institution}</Text> : null}
                {periodLabel(r.metadata) ? <Text style={styles.meta}>{periodLabel(r.metadata)}</Text> : null}
              </FoldCard>
            </Pressable>
          ))}

          <Pressable
            style={[styles.danger, (deletingAll || rows.length === 0) && styles.disabled]}
            onPress={deleteAll}
            disabled={deletingAll || rows.length === 0}
            testID="statements-delete-all-button"
          >
            {deletingAll ? <ActivityIndicator color={financeColors.negative} /> : <Text style={styles.dangerText}>Delete all my documents</Text>}
          </Pressable>
        </ScrollView>
      )}

      <Modal visible={!!picked} transparent animationType="fade" onRequestClose={() => !uploading && setPicked(null)}>
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>Is this PDF password-protected?</Text>
            <Text style={styles.meta} numberOfLines={1}>{picked?.name}</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Password (leave empty if none)"
              placeholderTextColor={financeColors.inkFaint}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              testID="statements-password-input"
            />
            {uploadError ? <Text style={styles.error} testID="statements-upload-error">{uploadError}</Text> : null}
            <View style={styles.sheetActions}>
              <Pressable style={styles.secondary} onPress={() => setPicked(null)} disabled={uploading} testID="statements-upload-cancel">
                <Text style={styles.secondaryText}>Cancel</Text>
              </Pressable>
              <Pressable style={[styles.primary, { flex: 1 }, uploading && styles.disabled]} onPress={upload} disabled={uploading} testID="statements-upload-confirm">
                {uploading ? <ActivityIndicator color="#FBFBF6" /> : <Text style={styles.primaryText}>Upload</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  card: { padding: financeSpace.lg, gap: 2 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: financeSpace.md },
  title: { ...financeType.rowLabel, fontSize: 15, fontWeight: "700", flex: 1 } as any,
  meta: { fontSize: 12, color: financeColors.inkMuted },
  error: { fontSize: 13, color: financeColors.negative },
  primary: { backgroundColor: financeColors.ink, minHeight: 48, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center" },
  primaryText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700", letterSpacing: 0.3 },
  secondary: { minHeight: 48, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", justifyContent: "center" },
  secondaryText: { color: financeColors.ink, fontSize: 14, fontWeight: "600" },
  danger: { marginTop: financeSpace.xl, minHeight: 48, borderRadius: financeRadius.pill, borderWidth: 1, borderColor: financeColors.negative, alignItems: "center", justifyContent: "center" },
  dangerText: { color: financeColors.negative, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  backdrop: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "center", padding: financeSpace.xl },
  sheet: { backgroundColor: financeColors.card, borderRadius: financeRadius.lg, padding: financeSpace.xl, gap: financeSpace.md },
  sheetTitle: { fontSize: 17, fontWeight: "700", color: financeColors.ink },
  input: { borderWidth: 1, borderColor: financeColors.cardBorder, borderRadius: financeRadius.md, paddingHorizontal: financeSpace.md, minHeight: 48, fontSize: 15, color: financeColors.ink },
  sheetActions: { flexDirection: "row", gap: financeSpace.md },
});
