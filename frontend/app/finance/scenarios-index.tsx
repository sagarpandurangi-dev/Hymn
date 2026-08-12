import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";

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
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader
        title="Scenarios"
        subtitle="Sandbox · never touches real data"
        right={
          <Pressable onPress={create} hitSlop={12} testID="sc-new" style={styles.iconBtn}>
            <Ionicons name="add" size={20} color={financeColors.ink} />
          </Pressable>
        }
      />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No scenarios yet. Tap + to create one.</Text></FoldCard>
          ) : (
            <FoldCard>
              {rows.map((s, idx) => (
                <FoldRow
                  key={s.id}
                  first={idx === 0}
                  onPress={() => router.push(`/finance/scenarios-detail?id=${s.id}`)}
                  label={s.name}
                  meta={`${s.currency} · updated ${s.updated_at?.slice(0, 10)}`}
                  right={
                    <View style={{ flexDirection: "row", alignItems: "center", gap: financeSpace.md }}>
                      <Pressable onPress={() => { setRenameFor(s); setRenameText(s.name); }} hitSlop={10} testID={`sc-rename-${s.id}`}>
                        <Ionicons name="pencil-outline" size={15} color={financeColors.inkMuted} />
                      </Pressable>
                      <Pressable onPress={() => duplicate(s.id)} hitSlop={10} testID={`sc-dup-${s.id}`}>
                        <Ionicons name="copy-outline" size={15} color={financeColors.inkMuted} />
                      </Pressable>
                      <Pressable onPress={() => remove(s.id)} hitSlop={10} testID={`sc-del-${s.id}`}>
                        <Ionicons name="trash-outline" size={15} color={financeColors.danger} />
                      </Pressable>
                    </View>
                  }
                />
              ))}
            </FoldCard>
          )}
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
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: financeColors.page, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.xl, paddingBottom: financeSpace.xxxl, gap: financeSpace.md },
  sheetTitle: { ...financeType.screenTitle, fontSize: 18 } as any,
  input: { backgroundColor: "#FFFFFF", borderRadius: financeRadius.sm, paddingHorizontal: financeSpace.lg, paddingVertical: financeSpace.md, fontSize: 15, color: financeColors.ink, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center" },
  primaryText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
});
