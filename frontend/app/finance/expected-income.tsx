import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import CurrencyPickerModal from "@/src/components/portfolio/CurrencyPickerModal";
import AccountPickerModal from "@/src/components/AccountPickerModal";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { CURRENCY_LABEL } from "@/src/lib/portfolio/constants";
import { FoldAmount, FoldCard, FoldPill, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";
import { toLocalTimezoneIso } from "@/src/lib/finance/occurredAt";

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
  // Correction 2: mark-received now requires an asset account +
  // occurred_at. State kept for the receive sheet.
  const [receiveTarget, setReceiveTarget] = useState<any | null>(null);
  const [receiveAccountId, setReceiveAccountId] = useState<string | null>(null);
  const [receiveAccountLabel, setReceiveAccountLabel] = useState<string>("Choose account");
  const [receiveAccountPickerOpen, setReceiveAccountPickerOpen] = useState(false);
  const [receiveDate, setReceiveDate] = useState<string>("");

  const load = useCallback(async () => { setLoading(true); try { setRows(await api.listExpectedIncome()); } catch { /* ignore */ } setLoading(false); }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => { (async () => { try { const st = await api.getPortfolioSetupStatus(); if (st?.reporting_currency) setCurrency(st.reporting_currency); } catch { /* ignore */ } })(); }, []);

  const save = async () => {
    setError(null);
    if (!title.trim() || !amount || !expectedDate) { setError("Title, amount and date are required."); return; }
    setSaving(true);
    try {
      const created = await api.createExpectedIncome({ title: title.trim(), amount, currency, expected_date: expectedDate, classification, description: description.trim() });
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

  const markReceived = (row: any) => {
    // Correction 2: open a small sheet to collect account + occurred_at.
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, "0");
    const dd = String(today.getDate()).padStart(2, "0");
    setReceiveTarget(row);
    setReceiveAccountId(null);
    setReceiveAccountLabel("Choose account");
    setReceiveDate(`${yyyy}-${mm}-${dd}`);
  };

  const submitReceived = async () => {
    if (!receiveTarget || !receiveAccountId || !receiveDate) return;
    try {
      const occ = toLocalTimezoneIso(receiveDate, "12:00");
      if (!occ) throw new Error("Invalid date");
      await api.markExpectedReceived(receiveTarget.id, {
        account_id: receiveAccountId,
        occurred_at: occ,
        event_date: receiveDate,
      });
      setReceiveTarget(null);
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "");
    }
  };
  const remove = async (id: string) => { try { await api.deleteExpectedIncome(id); load(); } catch (e: any) { Alert.alert("Error", e?.message || ""); } };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader
        title="Expected income"
        subtitle="One-time future income"
        right={
          <Pressable onPress={() => setAddOpen(true)} hitSlop={12} testID="ei-add" style={styles.iconBtn}>
            <Ionicons name="add" size={20} color={financeColors.ink} />
          </Pressable>
        }
      />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.note}>Add future expenses when planned. Treat future income cautiously until earned or confirmed.</Text>
          {rows.length === 0 ? (
            <FoldCard><Text style={styles.empty}>No expected income yet.</Text></FoldCard>
          ) : (
            <FoldCard>
              {rows.map((r, idx) => (
                <FoldRow
                  key={r.id}
                  first={idx === 0}
                  label={
                    <View style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <Text style={[financeType.rowLabel, { maxWidth: 180 }]} numberOfLines={1}>{r.title}</Text>
                      <FoldPill label={r.classification} tone={r.classification === "confirmed" ? "ok" : "neutral"} size="xs" />
                      {r.received ? <FoldPill label="Received" tone="ok" size="xs" /> : null}
                      {!r.received && r.included_in_forecast ? <FoldPill label="In forecast" tone="info" size="xs" /> : null}
                    </View>
                  }
                  meta={`${dateLabel(r.expected_date)}`}
                  right={
                    <View style={{ flexDirection: "row", alignItems: "center", gap: financeSpace.sm }}>
                      <FoldAmount currency={r.currency} value={formatMoney(r.amount)} tone="positive" />
                      {!r.received ? (
                        <Pressable onPress={() => markReceived(r)} style={styles.smallBtn} testID={`ei-received-${r.id}`}>
                          <Text style={styles.smallBtnText}>Received</Text>
                        </Pressable>
                      ) : null}
                      <Pressable onPress={() => remove(r.id)} hitSlop={12} testID={`ei-remove-${r.id}`} style={styles.iconTrash}>
                        <Ionicons name="trash-outline" size={14} color={financeColors.danger} />
                      </Pressable>
                    </View>
                  }
                />
              ))}
            </FoldCard>
          )}
        </ScrollView>
      )}

      <Modal visible={addOpen} animationType="slide" transparent onRequestClose={() => setAddOpen(false)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Add expected income</Text>
              <Pressable onPress={() => setAddOpen(false)} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            <Text style={styles.label}>TITLE</Text>
            <TextInput style={styles.input} value={title} onChangeText={setTitle} testID="ei-title" />
            <View style={{ flexDirection: "row", gap: financeSpace.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>AMOUNT</Text>
                <TextInput style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" testID="ei-amount" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>CURRENCY</Text>
                <Pressable style={styles.input} onPress={() => setPickerOpen(true)} testID="ei-currency">
                  <Text style={{ color: financeColors.ink }}>{CURRENCY_LABEL(currency)}</Text>
                </Pressable>
              </View>
            </View>
            <Text style={styles.label}>EXPECTED DATE</Text>
            <DateTimeField mode="date" value={expectedDate} onChange={setExpectedDate} testID="ei-date" />
            <Text style={styles.label}>CLASSIFICATION</Text>
            <View style={{ flexDirection: "row", gap: financeSpace.sm }}>
              {["confirmed", "expected"].map((c) => (
                <Pressable key={c} onPress={() => setClassification(c as any)} style={[styles.chip, classification === c && styles.chipSel]} testID={`ei-class-${c}`}>
                  <Text style={[styles.chipText, classification === c && styles.chipTextSel]}>{c}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.label}>DESCRIPTION (OPTIONAL)</Text>
            <TextInput style={styles.input} value={description} onChangeText={setDescription} multiline testID="ei-desc" />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable style={[styles.primary, saving && { opacity: 0.5 }]} disabled={saving} onPress={save} testID="ei-save">
              <Text style={styles.primaryText}>Save</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <CurrencyPickerModal visible={pickerOpen} selected={currency} onSelect={setCurrency} onClose={() => setPickerOpen(false)} />

      <Modal visible={!!confirmSheet} animationType="slide" transparent onRequestClose={() => setConfirmSheet(null)}>
        <View style={styles.sheetWrap}>
          <View style={styles.sheetCard}>
            <Text style={styles.sheetTitle}>Include in forecast?</Text>
            <Text style={styles.sheetBody}>Treat future income cautiously until it is earned or confirmed. Include this Expected income in the 12-month forecast? Months materially dependent on Expected income will show Low confidence.</Text>
            <View style={{ flexDirection: "row", gap: financeSpace.sm, marginTop: financeSpace.md }}>
              <Pressable style={styles.primary} onPress={() => confirmInclude(true)} testID="ei-include"><Text style={styles.primaryText}>Yes, include</Text></Pressable>
              <Pressable style={styles.secondary} onPress={() => confirmInclude(false)} testID="ei-exclude"><Text style={styles.secondaryText}>Keep excluded</Text></Pressable>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={!!receiveTarget} animationType="slide" transparent onRequestClose={() => setReceiveTarget(null)}>
        <KeyboardAvoidingView style={styles.sheetWrap} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.sheetCard}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Mark received</Text>
              <Pressable onPress={() => setReceiveTarget(null)} hitSlop={12}><Ionicons name="close" size={20} color={financeColors.ink} /></Pressable>
            </View>
            <Text style={styles.sheetBody}>Which asset account did this land in?</Text>
            <Text style={styles.label}>RECEIVING ACCOUNT</Text>
            <Pressable style={styles.input} onPress={() => setReceiveAccountPickerOpen(true)} testID="ei-receive-account">
              <Text style={{ color: receiveAccountId ? financeColors.ink : financeColors.inkFaint }}>{receiveAccountLabel}</Text>
            </Pressable>
            <Text style={styles.label}>RECEIVED ON</Text>
            <DateTimeField mode="date" value={receiveDate} onChange={setReceiveDate} testID="ei-receive-date" />
            <Pressable style={[styles.primary, (!receiveAccountId || !receiveDate) && { opacity: 0.5 }]} disabled={!receiveAccountId || !receiveDate} onPress={submitReceived} testID="ei-receive-submit">
              <Text style={styles.primaryText}>Confirm received</Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <AccountPickerModal
        visible={receiveAccountPickerOpen}
        currency={receiveTarget?.currency || currency}
        selectedId={receiveAccountId}
        onSelect={async (id) => {
          setReceiveAccountId(id);
          if (!id) { setReceiveAccountLabel("Assign later"); return; }
          try {
            const rows = await api.listFinancialAccounts();
            const m = rows.find((r) => r.id === id);
            setReceiveAccountLabel(m ? `${m.name} (${m.currency})` : "Account selected");
          } catch { setReceiveAccountLabel("Account selected"); }
        }}
        onClose={() => setReceiveAccountPickerOpen(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  note: { fontSize: 12, color: financeColors.inkMuted, fontStyle: "italic", lineHeight: 17, paddingHorizontal: 2 },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  smallBtn: { paddingHorizontal: financeSpace.md, paddingVertical: 5, borderRadius: financeRadius.pill, backgroundColor: financeColors.accent },
  smallBtnText: { color: "#FFFFFF", fontSize: 10.5, fontWeight: "700", letterSpacing: 0.4 },
  iconTrash: { padding: 4 },
  sheetWrap: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheetCard: { backgroundColor: financeColors.page, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.xl, paddingBottom: financeSpace.xxxl, gap: financeSpace.sm },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sheetTitle: { ...financeType.screenTitle, fontSize: 18 } as any,
  sheetBody: { ...financeType.body, color: financeColors.inkMuted, marginTop: 4 } as any,
  label: { ...financeType.sectionLabel, marginTop: financeSpace.sm } as any,
  input: { backgroundColor: "#FFFFFF", borderRadius: financeRadius.sm, paddingHorizontal: financeSpace.lg, paddingVertical: financeSpace.md, fontSize: 15, color: financeColors.ink, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  chip: { paddingHorizontal: financeSpace.md, paddingVertical: financeSpace.sm, borderRadius: financeRadius.pill, backgroundColor: "#FFFFFF", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  chipSel: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipText: { fontSize: 12.5, color: financeColors.ink, fontWeight: "600" },
  chipTextSel: { color: "#FBFBF6" },
  error: { color: financeColors.danger, fontSize: 12.5, marginTop: financeSpace.sm },
  primary: { backgroundColor: financeColors.ink, paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, alignItems: "center", flex: 1, marginTop: financeSpace.md },
  primaryText: { color: "#FBFBF6", fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  secondary: { paddingVertical: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", flex: 1, marginTop: financeSpace.md },
  secondaryText: { color: financeColors.ink, fontSize: 13, fontWeight: "600" },
});
