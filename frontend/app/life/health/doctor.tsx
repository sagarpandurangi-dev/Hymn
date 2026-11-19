import { useCallback, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Share, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import { HealthHeader, hs, humanize, niceDay } from "@/src/components/health/ui";
import { showToast } from "@/src/lib/toast";
import { colors, spacing } from "@/src/lib/theme";

const MAX_Q = 10;
const fmt = (v: any) => {
  const n = Number(v);
  return v == null ? "—" : Number.isFinite(n) ? n.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : String(v);
};
const src = (s?: string) => (s ? s.replace(/_/g, " ") : "");

function Section({ title, children, testID }: { title: string; children: React.ReactNode; testID: string }) {
  return (
    <View style={{ gap: 4, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider }} testID={testID}>
      <Text style={hs.section}>{title.toUpperCase()}</Text>
      {children}
    </View>
  );
}
const Line = ({ children }: { children: React.ReactNode }) => <Text style={[hs.body, { color: colors.onSurface }]}>{children}</Text>;
const None = () => <Text style={hs.muted}>None recorded</Text>;
const list = (xs: any[] = []) => (xs.length ? xs.map((x, i) => <Line key={i}>• {typeof x === "string" ? humanize(x) : x.name ?? x.label ?? JSON.stringify(x)}</Line>) : <None />);

export default function DoctorSummaryScreen() {
  const [data, setData] = useState<any>(null);
  const [includePrivate, setIncludePrivate] = useState(false);
  const [error, setError] = useState("");
  const [sharing, setSharing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [questions, setQuestions] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [savingQ, setSavingQ] = useState(false);

  const load = useCallback(async (inc: boolean) => {
    try {
      const d = await api.getDoctorSummary(inc);
      setData(d);
      setQuestions(d?.questions ?? []);
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your summary.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(includePrivate); }, [load, includePrivate]));

  const share = async () => {
    setSharing(true);
    try {
      const text = await api.getDoctorSummaryText(includePrivate);
      await Share.share({ message: String(text), title: "Health summary" });
    } catch (e) {
      const err = e as ApiError;
      if (err?.message) setError(err.message);
    } finally {
      setSharing(false);
    }
  };

  /** The profile PUT replaces everything, so read the full profile and send it back with new questions. */
  const saveQuestions = async () => {
    setSavingQ(true);
    try {
      const profile = await api.getHealthProfile();
      const { consented_at: _c, updated_at: _u, ...rest } = profile ?? {};
      await api.saveHealthProfile({ ...rest, consent: true, doctor_questions: questions.slice(0, MAX_Q) });
      setEditing(false);
      showToast("Questions saved.");
      await load(includePrivate);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save your questions.");
    } finally {
      setSavingQ(false);
    }
  };
  const addQ = () => {
    const t = q.trim();
    if (!t || questions.length >= MAX_Q) return;
    setQuestions([...questions, t]);
    setQ("");
  };

  const d = data ?? {};
  const about = [d.name, d.age ? `${d.age} years` : "", d.sex ? humanize(d.sex) : "", d.pregnant_or_breastfeeding ? "Pregnant or breastfeeding" : ""].filter(Boolean).join(" · ");
  const lab = d.latest_lab_report;

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="doctor-summary-screen">
      <HealthHeader title="For my doctor" testID="doctor-summary" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          {!data ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
            <>
              {d.rules_reviewed === false ? <DraftNote /> : null}
              {error ? <Text style={hs.error}>{error}</Text> : null}
              <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
                <Pressable style={[hs.primary, { flex: 1 }, sharing && { opacity: 0.5 }]} onPress={share} disabled={sharing} testID="doctor-share">
                  {sharing ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Share as text</Text>}
                </Pressable>
              </View>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 }}>
                <Text style={[hs.body, { color: colors.onSurface }]}>Include private habits</Text>
                <Switch value={includePrivate} onValueChange={setIncludePrivate} testID="doctor-include-private" />
              </View>

              <View style={[hs.card, { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.divider }]} testID="doctor-page">
                <Text style={[hs.h, { fontSize: 18 }]}>Health summary</Text>
                <Text style={hs.muted}>Prepared {niceDay(d.prepared_on)} with the Hymn app</Text>

                <Section title="About" testID="doctor-about">
                  <Line>{about || "—"}</Line>
                  <Line>Smoking: {d.smoking ? humanize(d.smoking) : "—"} · Alcohol: {fmt(d.alcohol_drinks_per_week ?? 0)} drinks a week</Line>
                </Section>
                <Section title="Conditions" testID="doctor-conditions">{list(d.conditions)}</Section>
                <Section title="Medicines" testID="doctor-medicines">{list(d.medicines)}</Section>
                <Section title="Family history" testID="doctor-family">{list(d.family_history)}</Section>
                <Section title="Latest readings" testID="doctor-readings">
                  {(d.readings ?? []).length ? d.readings.map((r: any, i: number) => (
                    <View key={i} style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{r.label}</Text>
                      <Text style={[hs.body, { color: colors.onSurface }]}>{fmt(r.value)} {r.unit}</Text>
                      <Text style={[hs.muted, { width: 110, textAlign: "right" }]}>{niceDay(r.date)} · {src(r.source)}</Text>
                    </View>
                  )) : <None />}
                </Section>
                <Section title="Changes over 90 days" testID="doctor-changes">
                  {(d.changes_90_days ?? []).length ? d.changes_90_days.map((c: any, i: number) => (
                    <Line key={i}>• {c.label}: {fmt(c.before)} → {fmt(c.after)}{c.unit ? ` ${c.unit}` : ""}</Line>
                  )) : <None />}
                </Section>
                <Section title="Symptoms logged" testID="doctor-symptoms">
                  {(d.symptoms_90_days ?? []).length ? d.symptoms_90_days.map((s: any, i: number) => <Line key={i}>• {niceDay(s.date)}: {s.what}</Line>) : <None />}
                </Section>
                <Section title="Habits" testID="doctor-habits">
                  {(d.habits ?? []).length ? d.habits.map((h: any, i: number) => (
                    <Line key={i}>• {h.label ?? humanize(String(h.kind ?? ""))}{h.goal ? ` — ${h.goal === "quit" ? "quitting" : "cutting down"}` : ""}{h.progress?.days_logged ? ` (${h.progress.days_on_track} of ${h.progress.days_logged} days on track)` : ""}</Line>
                  )) : <None />}
                </Section>
                <Section title="Check-ups due" testID="doctor-checkups">
                  {(d.checkups_due ?? []).length ? d.checkups_due.map((c: any, i: number) => <Line key={i}>• {c.label}{c.last_done ? ` (last ${niceDay(c.last_done)})` : ""}</Line>) : <None />}
                </Section>
                <Section title="Latest lab report" testID="doctor-lab">
                  {lab ? (
                    <>
                      <Text style={hs.muted}>{[niceDay(lab.report_date), lab.lab].filter(Boolean).join(" · ")}</Text>
                      {(lab.results ?? []).map((r: any, i: number) => (
                        <View key={i} style={{ flexDirection: "row", gap: spacing.sm }}>
                          <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{r.test_name}</Text>
                          <Text style={[hs.body, { color: colors.onSurface }]}>{r.value} {r.unit}{r.flag ? ` ${r.flag}` : ""}</Text>
                          <Text style={[hs.muted, { width: 80, textAlign: "right" }]}>{r.reference_range}</Text>
                        </View>
                      ))}
                    </>
                  ) : <None />}
                </Section>
                <Section title="My questions" testID="doctor-questions">
                  {editing ? (
                    <View style={{ gap: spacing.sm }}>
                      {questions.map((x, i) => (
                        <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                          <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{i + 1}. {x}</Text>
                          <Pressable onPress={() => setQuestions(questions.filter((_, j) => j !== i))} hitSlop={8} testID={`doctor-question-remove-${i}`}><Ionicons name="close" size={18} color={colors.onSurfaceSecondary} /></Pressable>
                        </View>
                      ))}
                      {questions.length < MAX_Q ? (
                        <View style={{ flexDirection: "row", gap: spacing.sm }}>
                          <TextInput style={[hs.input, { flex: 1 }]} value={q} onChangeText={setQ} placeholder="Something you want to ask" placeholderTextColor={colors.onSurfaceTertiary} onSubmitEditing={addQ} returnKeyType="done" testID="doctor-question-input" />
                          <Pressable style={[hs.secondary, { paddingHorizontal: spacing.lg }]} onPress={addQ} testID="doctor-question-add"><Text style={hs.secondaryText}>Add</Text></Pressable>
                        </View>
                      ) : <Text style={hs.muted}>Up to {MAX_Q} questions.</Text>}
                      <Pressable style={[hs.primary, savingQ && { opacity: 0.5 }]} onPress={saveQuestions} disabled={savingQ} testID="doctor-questions-save">
                        {savingQ ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save questions</Text>}
                      </Pressable>
                    </View>
                  ) : (
                    <>
                      {questions.length ? questions.map((x, i) => <Line key={i}>{i + 1}. {x}</Line>) : <Text style={hs.muted}>No questions yet</Text>}
                      <Pressable style={{ minHeight: 40, justifyContent: "center" }} onPress={() => setEditing(true)} testID="doctor-questions-edit">
                        <Text style={[hs.body, { color: colors.brandPrimary, fontWeight: "600" }]}>Edit my questions for the doctor</Text>
                      </Pressable>
                    </>
                  )}
                </Section>
                {d.note ? <Text style={[hs.muted, { marginTop: spacing.sm }]}>{d.note}</Text> : null}
              </View>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
