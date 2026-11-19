import { useCallback, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { pickPdf, PickedFile } from "@/src/utils/upload";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import CasPreviewCard, { periodText } from "@/src/components/finance/CasPreviewCard";
import CasAccountLinker, { AccountChoice, toApplyPayload } from "@/src/components/finance/CasAccountLinker";
import { FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const HOW_TO = [
  "Mutual funds: request a Consolidated Account Statement on the CAMS or KFintech website (detailed, with transactions); the password is the one you set.",
  "Shares and demat: NSDL or CDSL email it every month; the password is usually your PAN in capitals.",
];

const missingName = (m: any) => (typeof m === "string" ? m : m?.name ?? m?.account_name ?? "An investment");

export default function CasImportScreen() {
  const [file, setFile] = useState<(PickedFile & { name?: string }) | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"" | "reading" | "applying">("");
  const [error, setError] = useState("");
  const [premium, setPremium] = useState(true);
  const [preview, setPreview] = useState<any>(null);
  const [choices, setChoices] = useState<Record<string, AccountChoice>>({});
  const [result, setResult] = useState<any>(null);
  const [past, setPast] = useState<any[]>([]);

  const loadPast = useCallback(async () => {
    try {
      const res: any = await api.casList();
      setPast(Array.isArray(res) ? res : res?.statements ?? res?.items ?? []);
    } catch (e) {
      if ((e as ApiError).status === 403) setPremium(false);
    }
  }, []);
  useFocusEffect(useCallback(() => { loadPast(); }, [loadPast]));

  const fail = (e: unknown) => {
    const err = e as ApiError;
    if (err.status === 403) setPremium(false);
    else setError(err.message || "Something went wrong. Try again.");
  };

  const choose = async () => {
    setError("");
    try {
      const f = await pickPdf();
      if (f) setFile(f);
    } catch {
      setError("Couldn't open that file.");
    }
  };

  const read = async () => {
    if (!file || !password) return;
    setBusy("reading");
    setError("");
    setResult(null);
    try {
      const p = await api.casPreview(file.base64, password);
      setPreview(p);
      setChoices({});
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const apply = async () => {
    if (Object.values(choices).some((c) => c.mode === "same" && !c.lineKey)) {
      setError("Pick which fund in this statement is the same, or choose “Something else”.");
      return;
    }
    const id = preview?.id ?? preview?.statement_id ?? preview?.cas_id;
    if (!id) { setError("This preview can't be applied."); return; }
    setBusy("applying");
    setError("");
    try {
      setResult(await api.casApply(String(id), toApplyPayload(choices)));
      setPreview(null);
      setFile(null);
      setPassword("");
      loadPast();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const others: any[] = preview?.your_other_investment_accounts ?? [];

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Add investments" subtitle="From a mutual fund or demat statement" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {!premium ? (
            <FoldCard testID="cas-premium">
              <View style={styles.pad}>
                <Ionicons name="sparkles-outline" size={20} color={financeColors.ink} />
                <Text style={styles.h}>Premium feature</Text>
                <Text style={styles.body}>Importing investment statements is part of Premium.</Text>
              </View>
            </FoldCard>
          ) : (
            <>
              {result ? (
                <FoldCard testID="cas-result">
                  <View style={styles.pad}>
                    <Text style={styles.h}>Added {Number(result.added ?? 0)}, updated {Number(result.updated ?? 0)}</Text>
                    {(result.missing ?? []).length > 0 ? (
                      <>
                        <Text style={styles.body}>Not in this statement — maybe sold?</Text>
                        {(result.missing as any[]).map((m, i) => <Text key={i} style={styles.bullet} testID={`cas-missing-${i}`}>• {missingName(m)}</Text>)}
                      </>
                    ) : null}
                  </View>
                </FoldCard>
              ) : null}

              {!preview ? (
                <>
                  <FoldCard>
                    <View style={styles.pad}>
                      <Text style={styles.h}>Where to get the PDF</Text>
                      {HOW_TO.map((t) => <Text key={t} style={styles.body}>{t}</Text>)}
                    </View>
                  </FoldCard>
                  <FoldCard style={{ marginTop: financeSpace.lg }}>
                    <View style={styles.pad}>
                      <Pressable style={styles.secondary} onPress={choose} disabled={!!busy} testID="cas-pick-pdf">
                        <Ionicons name="document-attach-outline" size={18} color={financeColors.ink} />
                        <Text style={styles.secondaryText}>{file ? "PDF chosen — change" : "Choose PDF"}</Text>
                      </Pressable>
                      <TextInput
                        style={styles.input}
                        value={password}
                        onChangeText={(v) => { setPassword(v); setError(""); }}
                        placeholder="Statement password"
                        placeholderTextColor={financeColors.inkMuted}
                        secureTextEntry
                        autoCapitalize="none"
                        autoCorrect={false}
                        testID="cas-password"
                      />
                      <Pressable style={[styles.primary, (!file || !password || !!busy) && { opacity: 0.45 }]} onPress={read} disabled={!file || !password || !!busy} testID="cas-read">
                        {busy === "reading" ? <ActivityIndicator color={financeColors.card} /> : <Text style={styles.primaryText}>Read statement</Text>}
                      </Pressable>
                      {busy === "reading" ? <Text style={styles.body} testID="cas-reading">Reading your statement… this can take a few seconds.</Text> : null}
                    </View>
                  </FoldCard>
                </>
              ) : (
                <View style={{ gap: financeSpace.lg }}>
                  {preview.already_applied ? (
                    <View style={styles.notice} testID="cas-already-applied">
                      <Ionicons name="information-circle-outline" size={16} color={financeColors.ink} />
                      <Text style={styles.noticeText}>This statement is already in your money book.</Text>
                    </View>
                  ) : null}
                  <CasPreviewCard preview={preview} />
                  {others.length > 0 ? (
                    <CasAccountLinker
                      accounts={others}
                      lines={preview.lines ?? []}
                      choices={choices}
                      onChange={(id, c) => setChoices({ ...choices, [id]: c })}
                    />
                  ) : null}
                  <Pressable style={[styles.primary, (!!busy || preview.already_applied) && { opacity: 0.45 }]} onPress={apply} disabled={!!busy || !!preview.already_applied} testID="cas-apply">
                    {busy === "applying" ? <ActivityIndicator color={financeColors.card} /> : <Text style={styles.primaryText}>Add to my money book</Text>}
                  </Pressable>
                  <Pressable style={styles.link} onPress={() => setPreview(null)} disabled={!!busy} testID="cas-back">
                    <Text style={styles.linkText}>Choose a different statement</Text>
                  </Pressable>
                </View>
              )}
              {error ? <Text style={styles.error} testID="cas-error">{error}</Text> : null}

              {past.length > 0 ? (
                <View style={{ marginTop: financeSpace.xl }} testID="cas-past">
                  <FoldSectionHeader label="Past statements" />
                  <FoldCard>
                    {past.map((p, i) => (
                      <FoldRow
                        key={String(p.id ?? i)}
                        first={i === 0}
                        label={`${p.source ?? "Statement"}${periodText(p) ? ` · ${periodText(p)}` : ""}`}
                        meta={[
                          p.investor_name ?? p.investor?.name,
                          (p.applied_at ?? p.created_at) ? dateLabel(String(p.applied_at ?? p.created_at).slice(0, 10)) : "",
                        ].filter(Boolean).join(" · ")}
                        right={p.total != null || p.total_value != null ? <Text style={styles.pastTotal}>{reportMoney(p.currency ?? "INR", p.total ?? p.total_value)}</Text> : undefined}
                        testID={`cas-past-${i}`}
                      />
                    ))}
                  </FoldCard>
                </View>
              ) : null}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.lg, paddingBottom: financeSpace.xxxl * 2 },
  pad: { padding: financeSpace.lg, gap: financeSpace.sm },
  h: { fontSize: 16, fontWeight: "700", color: financeColors.ink },
  body: { fontSize: 14, lineHeight: 20, color: financeColors.inkMuted },
  bullet: { fontSize: 14, color: financeColors.ink },
  input: { minHeight: 48, borderWidth: 1, borderColor: financeColors.divider, borderRadius: 10, paddingHorizontal: financeSpace.md, fontSize: 15, color: financeColors.ink },
  primary: { minHeight: 50, borderRadius: 999, backgroundColor: financeColors.ink, alignItems: "center", justifyContent: "center" },
  primaryText: { color: financeColors.card, fontSize: 15, fontWeight: "700" },
  secondary: { minHeight: 48, borderRadius: 10, borderWidth: 1, borderColor: financeColors.divider, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  secondaryText: { fontSize: 15, fontWeight: "600", color: financeColors.ink },
  notice: { flexDirection: "row", gap: 8, alignItems: "center", padding: financeSpace.md, borderRadius: 10, backgroundColor: financeColors.card, borderWidth: 1, borderColor: financeColors.divider },
  noticeText: { flex: 1, fontSize: 14, color: financeColors.ink },
  link: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  linkText: { fontSize: 14, fontWeight: "600", color: financeColors.inkMuted },
  error: { fontSize: 13, color: financeColors.negative, marginTop: financeSpace.md },
  pastTotal: { fontSize: 14, fontWeight: "700", color: financeColors.ink },
});
