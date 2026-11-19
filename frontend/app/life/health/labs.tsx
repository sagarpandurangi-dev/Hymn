import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import { HealthHeader, hs, niceDay, statusColour } from "@/src/components/health/ui";
import { pickImage, pickPdf, PickedFile } from "@/src/utils/upload";
import { colors, spacing } from "@/src/lib/theme";

const confirmDelete = (ok: () => void) => {
  const body = "Delete this lab report and its saved values?";
  if (Platform.OS === "web") { if (window.confirm(body)) ok(); return; }
  Alert.alert("Delete report", body, [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: ok }]);
};

const BLANK = { test_name: "", value: "", unit: "", reference_range: "", flag: "", metric: null };

function ResultLine({ r, onChange, onRemove, i }: { r: any; onChange: (r: any) => void; onRemove: () => void; i: number }) {
  const set = (k: string, v: string) => onChange({ ...r, [k]: v });
  return (
    <View style={{ gap: 6, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider }} testID={`lab-line-${i}`}>
      {r.check ? (
        <View style={{ flexDirection: "row", gap: 6, alignItems: "flex-start" }} testID={`lab-line-check-${i}`}>
          <Ionicons name="alert-circle-outline" size={16} color={colors.warning} style={{ marginTop: 2 }} />
          <Text style={[hs.muted, { flex: 1, color: colors.warning }]}>{typeof r.check === "string" ? r.check : "Please check this line against your report."}</Text>
        </View>
      ) : null}
      <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
        <TextInput style={[hs.input, { flex: 1, minHeight: 40 }]} value={r.test_name} onChangeText={(v) => set("test_name", v)} placeholder="Test name" placeholderTextColor={colors.onSurfaceTertiary} testID={`lab-line-name-${i}`} />
        <Pressable onPress={onRemove} hitSlop={8} accessibilityLabel="Remove line" testID={`lab-line-remove-${i}`}><Ionicons name="close" size={18} color={colors.onSurfaceSecondary} /></Pressable>
      </View>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <TextInput style={[hs.input, { flex: 1, minHeight: 40 }]} value={String(r.value ?? "")} onChangeText={(v) => set("value", v)} placeholder="Value" placeholderTextColor={colors.onSurfaceTertiary} testID={`lab-line-value-${i}`} />
        <TextInput style={[hs.input, { flex: 1, minHeight: 40 }]} value={r.unit ?? ""} onChangeText={(v) => set("unit", v)} placeholder="Unit" placeholderTextColor={colors.onSurfaceTertiary} testID={`lab-line-unit-${i}`} />
      </View>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <TextInput style={[hs.input, { flex: 1, minHeight: 40 }]} value={r.reference_range ?? ""} onChangeText={(v) => set("reference_range", v)} placeholder="Reference range" placeholderTextColor={colors.onSurfaceTertiary} testID={`lab-line-range-${i}`} />
        <TextInput style={[hs.input, { width: 64, minHeight: 40, textAlign: "center" }]} value={r.flag ?? ""} onChangeText={(v) => set("flag", v)} placeholder="Flag" placeholderTextColor={colors.onSurfaceTertiary} testID={`lab-line-flag-${i}`} />
      </View>
      {r.metric && r.hymn_value != null ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <View style={[hs.dot, { backgroundColor: statusColour(r.status) }]} />
          <Text style={hs.muted}>Hymn reads this as {r.hymn_value} {r.hymn_unit}{r.why ? ` · ${r.why}` : ""}</Text>
        </View>
      ) : null}
    </View>
  );
}

export default function LabsScreen() {
  const [reports, setReports] = useState<any[] | null>(null);
  const [draft, setDraft] = useState<{ report_date: string; lab: string; results: any[]; note?: string } | null>(null);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.listLabReports();
      setReports(Array.isArray(r) ? r : []);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your reports.");
      setReports([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const read = async (file: PickedFile | null) => {
    if (!file) return;
    setReading(true);
    setError("");
    setMsg("");
    try {
      const res = await api.readLabReport(file.base64, file.mediaType);
      if (res?.is_lab_report === false) {
        setMsg("That doesn't look like a lab report. You can type the values in instead.");
        setDraft({ report_date: "", lab: "", results: [{ ...BLANK }] });
      } else {
        setDraft({ report_date: res?.report_date ?? "", lab: res?.lab ?? "", results: res?.results?.length ? res.results : [{ ...BLANK }], note: res?.note });
      }
    } catch (e) {
      const err = e as ApiError;
      setMsg(err.status === 503 ? "Couldn't read it — you can type values in." : err.message || "Couldn't read it — you can type values in.");
      setDraft({ report_date: "", lab: "", results: [{ ...BLANK }] });
    } finally {
      setReading(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setError("");
    if (!draft.report_date) { setError("Add the report date."); return; }
    const results = draft.results.filter((r) => String(r.test_name ?? "").trim() && String(r.value ?? "").trim());
    if (results.length === 0) { setError("Add at least one test with a value."); return; }
    setBusy(true);
    try {
      await api.saveLabReport({ report_date: draft.report_date, lab: draft.lab || null, results });
      setDraft(null);
      setMsg("Report saved.");
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const remove = (id: string) => confirmDelete(async () => {
    try {
      await api.deleteLabReport(id);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete. Try again.");
    }
  });

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="labs-screen">
      <HealthHeader title="Lab reports" testID="labs" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <Text style={hs.body}>Optional. If you have a recent blood test, Hymn can read it so your check-ups and suggestions fit you better.</Text>
          {msg ? <Text style={[hs.body, { color: colors.onSurface }]} testID="labs-message">{msg}</Text> : null}
          {error ? <Text style={hs.error} testID="labs-error">{error}</Text> : null}

          {draft ? (
            <View style={hs.card} testID="lab-draft">
              <Text style={hs.h}>Check and save</Text>
              {draft.note ? <Text style={hs.muted}>{draft.note}</Text> : null}
              <Text style={hs.label}>Report date</Text>
              <DateTimeField mode="date" value={draft.report_date} onChange={(v) => setDraft({ ...draft, report_date: v })} testID="lab-report-date" />
              <Text style={hs.label}>Lab (optional)</Text>
              <TextInput style={hs.input} value={draft.lab} onChangeText={(v) => setDraft({ ...draft, lab: v })} placeholder="e.g. City Diagnostics" placeholderTextColor={colors.onSurfaceTertiary} testID="lab-name" />
              <Text style={hs.label}>Results</Text>
              {draft.results.map((r, i) => (
                <ResultLine key={i} i={i} r={r} onChange={(nr) => setDraft({ ...draft, results: draft.results.map((x, j) => (j === i ? nr : x)) })} onRemove={() => setDraft({ ...draft, results: draft.results.filter((_, j) => j !== i) })} />
              ))}
              <Pressable style={[hs.chip, { alignSelf: "flex-start", marginTop: spacing.sm }]} onPress={() => setDraft({ ...draft, results: [...draft.results, { ...BLANK }] })} testID="lab-add-line">
                <Text style={hs.chipText}>+ Add a line</Text>
              </Pressable>
              <Pressable style={[hs.primary, { marginTop: spacing.md }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="lab-save">
                {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
              </Pressable>
              <Pressable style={{ minHeight: 44, alignItems: "center", justifyContent: "center" }} onPress={() => setDraft(null)} testID="lab-cancel">
                <Text style={hs.body}>Cancel</Text>
              </Pressable>
            </View>
          ) : (
            <View style={{ gap: spacing.sm }}>
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <Pressable style={[hs.secondary, { flex: 1 }, reading && { opacity: 0.5 }]} disabled={reading} onPress={async () => read(await pickPdf())} testID="lab-upload-pdf">
                  <Ionicons name="document-outline" size={18} color={colors.onSurface} />
                  <Text style={hs.secondaryText}>PDF</Text>
                </Pressable>
                <Pressable style={[hs.secondary, { flex: 1 }, reading && { opacity: 0.5 }]} disabled={reading} onPress={async () => read(await pickImage())} testID="lab-upload-photo">
                  <Ionicons name="image-outline" size={18} color={colors.onSurface} />
                  <Text style={hs.secondaryText}>Photo</Text>
                </Pressable>
              </View>
              <Pressable style={{ minHeight: 40, justifyContent: "center" }} onPress={() => setDraft({ report_date: "", lab: "", results: [{ ...BLANK }] })} testID="lab-type-in">
                <Text style={[hs.body, { color: colors.brandPrimary, fontWeight: "600" }]}>Or type the values in</Text>
              </Pressable>
              {reading ? <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}><ActivityIndicator color={colors.onSurfaceTertiary} /><Text style={hs.muted}>Reading your report…</Text></View> : null}
            </View>
          )}

          <View style={{ gap: spacing.sm }}>
            <Text style={hs.section}>PAST REPORTS</Text>
            {reports === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : reports.length === 0 ? (
              <Text style={hs.muted} testID="labs-empty">None yet.</Text>
            ) : reports.map((rep) => (
              <View key={rep.id} style={hs.card} testID={`lab-report-${rep.id}`}>
                <Pressable style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 }} onPress={() => setOpenId(openId === rep.id ? null : rep.id)} testID={`lab-report-open-${rep.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={[hs.h, { fontSize: 15 }]}>{niceDay(rep.report_date)}</Text>
                    <Text style={hs.muted}>{[rep.lab, `${(rep.results ?? []).length} tests`].filter(Boolean).join(" · ")}</Text>
                  </View>
                  <Ionicons name={openId === rep.id ? "chevron-up" : "chevron-down"} size={18} color={colors.onSurfaceSecondary} />
                </Pressable>
                {openId === rep.id ? (
                  <>
                    {(rep.results ?? []).map((r: any, i: number) => (
                      <View key={i} style={{ flexDirection: "row", gap: spacing.sm }}>
                        <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{r.test_name}</Text>
                        <Text style={hs.body}>{r.value} {r.unit}{r.flag ? ` ${r.flag}` : ""}</Text>
                      </View>
                    ))}
                    <Pressable style={{ minHeight: 40, justifyContent: "center" }} onPress={() => remove(rep.id)} testID={`lab-report-delete-${rep.id}`}>
                      <Text style={[hs.body, { color: colors.error, fontWeight: "600" }]}>Delete report</Text>
                    </Pressable>
                  </>
                ) : null}
              </View>
            ))}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
