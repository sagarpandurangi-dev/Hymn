import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { CURRENCY_LABEL } from "@/src/lib/portfolio/constants";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";

export default function ExpectedIncome() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [expectedDate, setExpectedDate] = useState("");
  const [classification, setClassification] = useState<"confirmed" | "expected">("expected");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmSheet, setConfirmSheet] = useState<any | null>(null);

  const load = useCallback(async () => { setLoading(true); try { setRows(await api.listExpectedIncome()); } catch { /* ignore */ } setLoading(false); }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => { (async () => { try { const st = await api.getPortfolioSetupStatus(); if (st?.reporting_currency) setCurrency(st.reporting_currency); } catch { /* ignore */ } })(); }, []);

  const save = async () => {
    setError(null);
    if (!title.trim() || !amount || !expectedDate) { setError("Title, amount and date are required."); return; }
    setSaving(true);
    try {
      const created = await api.createExpectedIncome({ title: title.trim(), amount, currency, expected_date: expectedDate, classification, description: description.trim() });
      // §22 — when Expected, gate inclusion behind a second confirmation.
      if (classification === "expected") setConfirmSheet(created);
      setAddOpen(false);
      setTitle(""); setAmount(""); setExpectedDate(""); setClassification("expected"); setDescription("");
      await load();
    } catch (e: any) { setError(e?.message || "Could not save"); } finally { setSaving(false); }
  };

  const confirmInclude = async (include: boolean) => {
    if (!confirmSheet) return;
    try { await api.confirmExpectedInclusion(confirmSheet.id, include); setConfirmSheet(null); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); }
  };

  const markReceived = async (id: string) => {
    try { await api.markExpectedReceived(id, {}); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); }
  };
  const remove = async (id: string) => { try { await api.deleteExpectedIncome(id); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <FinanceHeader title="Expected income" subtitle="One-time future income" right={<Pressable onPress={() => setAddOpen(true)} hitSlop={12} testID="ei-add"><Ionicons name="add" size={22} color={colors.onSurface} /></Pressable>} />
      {loading ? <ActivityIndicator style={{ marginTop: spacing.xxxl }} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.note}>It is prudent to add future expenses when planned, but to treat future income cautiously until it has been earned or confirmed.</Text>
          {rows.length === 0 && <Text style={styles.empty}>No expected income yet.</Text>}
          {rows.map((r) => (
            <View key={r.id} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{r.title}</Text>
                <Text style={styles.meta}>{r.currency} {formatMoney(r.amount)} · {dateLabel(r.expected_date)} · {r.classification} {r.included_in_forecast ? "· in forecast" : "· excluded"} {r.received ? "· RECEIVED" : ""}</Text>
              </View>
              {!r.received && <Pressable onPress={() => markReceived(r.id)} style={styles.smallBtn} testID={`ei-received-${r.id}`}><Text style={styles.smallBtnText}>Mark received</Text></Pressable>}
              <Pressable onPress={() => remove(r.id)} hitSlop={12} testID={`ei-remove-${r.id}`}><Ionicons name="trash-outline" size={16} color={colors.error} /></Pressable>
            </View>
          ))}
        </ScrollView>
      )}

      <Modal visible={addOpen} animationType="slide" transparent onRequestClose={() => setAddOpen(false)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}><Text style={styles.sheetTitle}>Add expected income</Text><Pressable onPress={() => setAddOpen(false)} hitSlop={12}><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable></View>
            <Text style={styles.label}>Title</Text><TextInput style={styles.input} value={title} onChangeText={setTitle} testID="ei-title" />
            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}><Text style={styles.label}>Amount</Text><TextInput style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="ei-amount" /></View>
              <View style={{ flex: 1 }}><Text style={styles.label}>Currency</Text><Pressable style={styles.input} onPress={() => setPickerOpen(true)} testID="ei-currency"><Text style={{ color: colors.onSurface }}>{CURRENCY_LABEL(currency)}</Text></Pressable></View>
            </View>
            <Text style={styles.label}>Expected date</Text><DateTimeField mode="date" value={expectedDate} onChange={setExpectedDate} testID="ei-date" />
            <Text style={styles.label}>Classification</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              {["confirmed", "expected"].map((c) => (
                <Pressable key={c} onPress={() => setClassification(c as any)} style={[styles.chip, classification === c && styles.chipSel]} testID={`ei-class-${c}`}><Text style={[styles.chipText, classification === c && styles.chipTextSel]}>{c}</Text></Pressable>
              ))}
            </View>
            <Text style={styles.label}>Description (optional)</Text><TextInput style={styles.input} value={description} onChangeText={setDescription} multiline testID="ei-desc" />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={save} testID="ei-save"><Text style={styles.primaryText}>Save</Text></Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <CurrencyPickerModal visible={pickerOpen} selected={currency} onSelect={setCurrency} onClose={() => setPickerOpen(false)} />

      {/* §22 second confirmation gate for Expected income */}
      <Modal visible={!!confirmSheet} animationType="slide" transparent onRequestClose={() => setConfirmSheet(null)}>
        <View style={styles.sheetWrap}>
          <View style={styles.sheetCard}>
            <Text style={styles.sheetTitle}>Include in forecast?</Text>
            <Text style={styles.sheetBody}>It is prudent to add future expenses when planned, but to treat future income cautiously until it has been earned or confirmed. Do you want to include this Expected income in your 12-month forecast? Months materially dependent on Expected income will show Low confidence.</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable style={styles.primary} onPress={() => confirmInclude(true)} testID="ei-include"><Text style={styles.primaryText}>Yes, include</Text></Pressable>
              <Pressable style={styles.secondary} onPress={() => confirmInclude(false)} testID="ei-exclude"><Text style={styles.secondaryText}>No, keep excluded</Text></Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, gap: spacing.md, paddingBottom: spacing.xxxl },
  note: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.md, backgroundColor: colors.brandTertiary, borderRadius: radius.sm, lineHeight: 18 },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic", padding: spacing.xl, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm },
  title: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  meta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  smallBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.brandPrimary },
  smallBtnText: { color: colors.onBrandPrimary, fontSize: 11, fontWeight: "700" },
  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.sm },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  sheetBody: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, marginTop: spacing.sm },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  chip: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  chipSel: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 13, color: colors.onBrandTertiary },
  chipTextSel: { color: colors.onBrandPrimary, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, marginTop: spacing.sm },
  primary: { backgroundColor: colors.onSurface, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, alignItems: "center", flex: 1, marginTop: spacing.md },
  primaryText: { color: colors.onSurfaceInverse, fontSize: 14, fontWeight: "700" },
  secondary: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", flex: 1, marginTop: spacing.md },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
});
