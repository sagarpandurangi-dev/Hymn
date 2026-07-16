import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import FinanceHeader from "@/src/components/finance/FinanceHeader";

export default function ScenariosIndex() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [renameFor, setRenameFor] = useState<any | null>(null);
  const [renameText, setRenameText] = useState("");

  const load = useCallback(async () => { setLoading(true); try { setRows(await api.listScenarios()); } catch { /* ignore */ } setLoading(false); }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    try {
      const s = await api.saveScenario({ name: `Scenario ${rows.length + 1}`, currency: "USD", assumptions: {} });
      router.push(`/finance/scenarios-detail?id=${s.id}`);
    } catch (e: any) { Alert.alert("Error", e?.message || ""); }
  };
  const duplicate = async (id: string) => { try { await api.duplicateScenario(id); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } };
  const remove = async (id: string) => { try { await api.deleteScenario(id); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } };
  const rename = async () => {
    if (!renameFor) return;
    try { await api.updateScenario(renameFor.id, { name: renameText.trim() || renameFor.name, currency: renameFor.currency, assumptions: renameFor.assumptions }); setRenameFor(null); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Scenarios" subtitle="Sandbox — never touches real data" right={<Pressable onPress={create} hitSlop={12} testID="sc-new"><Ionicons name="add" size={22} color={colors.onSurface} /></Pressable>} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 && <Text style={styles.empty}>No scenarios yet. Tap + to create one.</Text>}
          {rows.map((s) => (
            <View key={s.id} style={styles.row}>
              <Pressable style={{ flex: 1 }} onPress={() => router.push(`/finance/scenarios-detail?id=${s.id}`)}>
                <Text style={styles.title}>{s.name}</Text>
                <Text style={styles.meta}>{s.currency} · updated {s.updated_at?.slice(0, 10)}</Text>
              </Pressable>
              <Pressable onPress={() => { setRenameFor(s); setRenameText(s.name); }} hitSlop={12} testID={`sc-rename-${s.id}`}><Ionicons name="pencil-outline" size={16} color={colors.onSurfaceSecondary} /></Pressable>
              <Pressable onPress={() => duplicate(s.id)} hitSlop={12} testID={`sc-dup-${s.id}`}><Ionicons name="copy-outline" size={16} color={colors.onSurfaceSecondary} /></Pressable>
              <Pressable onPress={() => remove(s.id)} hitSlop={12} testID={`sc-del-${s.id}`}><Ionicons name="trash-outline" size={16} color={colors.error} /></Pressable>
            </View>
          ))}
        </ScrollView>
      )}
      <Modal visible={!!renameFor} animationType="slide" transparent onRequestClose={() => setRenameFor(null)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <Text style={styles.sheetTitle}>Rename scenario</Text>
            <TextInput value={renameText} onChangeText={setRenameText} style={styles.input} testID="sc-rename-input" />
            <Pressable style={styles.primary} onPress={rename} testID="sc-rename-save"><Text style={styles.primaryText}>Save</Text></Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.sm, paddingBottom: spacing.xxxl },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.xl, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm },
  title: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  meta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, borderRadius: radius.pill, alignItems: "center" },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700" },
});
