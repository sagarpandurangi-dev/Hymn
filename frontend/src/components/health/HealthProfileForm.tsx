/**
 * Health profile form. PUT /api/health/profile replaces the whole profile, so
 * this always sends every field.
 */
import { useState } from "react";
import { ActivityIndicator, Pressable, Switch, Text, TextInput, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import DateTimeField from "@/src/components/DateTimeField";
import { hs, humanize } from "@/src/components/health/ui";
import { colors, spacing } from "@/src/lib/theme";

type Opt = { code: string; label: string };

function Chips({ options, value, onToggle, testPrefix }: { options: Opt[]; value: string[]; onToggle: (c: string) => void; testPrefix: string }) {
  return (
    <View style={hs.chipRow}>
      {options.map((o) => {
        const on = value.includes(o.code);
        return (
          <Pressable key={o.code} style={[hs.chip, on && hs.chipOn]} onPress={() => onToggle(o.code)} testID={`${testPrefix}-${o.code}`}>
            <Text style={[hs.chipText, on && hs.chipTextOn]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Free-text list (medicines, questions for the doctor). */
function TagList({ value, onChange, placeholder, testID }: { value: string[]; onChange: (v: string[]) => void; placeholder: string; testID: string }) {
  const [text, setText] = useState("");
  const add = () => { const t = text.trim(); if (t && !value.includes(t)) onChange([...value, t]); setText(""); };
  return (
    <View style={{ gap: spacing.sm }}>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <TextInput style={[hs.input, { flex: 1 }]} value={text} onChangeText={setText} placeholder={placeholder} placeholderTextColor={colors.onSurfaceTertiary} onSubmitEditing={add} returnKeyType="done" testID={`${testID}-input`} />
        <Pressable style={[hs.secondary, { paddingHorizontal: spacing.lg }]} onPress={add} testID={`${testID}-add`}>
          <Text style={hs.secondaryText}>Add</Text>
        </Pressable>
      </View>
      {value.length > 0 ? (
        <View style={hs.chipRow}>
          {value.map((v) => (
            <Pressable key={v} style={[hs.chip, { flexDirection: "row", gap: 6 }]} onPress={() => onChange(value.filter((x) => x !== v))} testID={`${testID}-remove-${v}`}>
              <Text style={hs.chipText}>{v}</Text>
              <Ionicons name="close" size={14} color={colors.onSurfaceSecondary} />
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Toggle({ label, value, onChange, testID }: { label: string; value: boolean; onChange: (v: boolean) => void; testID: string }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md, minHeight: 48 }}>
      <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>{label}</Text>
      <Switch value={value} onValueChange={onChange} testID={testID} />
    </View>
  );
}

const SEX: Opt[] = [{ code: "female", label: "Female" }, { code: "male", label: "Male" }, { code: "other", label: "Other" }];
const SMOKING: Opt[] = [{ code: "never", label: "Never" }, { code: "former", label: "Used to" }, { code: "current", label: "Yes, now" }];

export default function HealthProfileForm({ initial, options, saveLabel, onSaved }: { initial: any; options: any; saveLabel: string; onSaved: (p: any) => void }) {
  const p = initial ?? {};
  const [dob, setDob] = useState<string>(p.date_of_birth ?? "");
  const [sex, setSex] = useState<string>(p.sex ?? "");
  const [height, setHeight] = useState<string>(p.height_cm != null ? String(p.height_cm) : "");
  const [conditions, setConditions] = useState<string[]>(p.conditions ?? []);
  const [medicines, setMedicines] = useState<string[]>(p.medicines ?? []);
  const [family, setFamily] = useState<string[]>(p.family_history ?? []);
  const [smoking, setSmoking] = useState<string>(p.smoking ?? "never");
  const [alcohol, setAlcohol] = useState<string>(p.alcohol_drinks_per_week != null ? String(p.alcohol_drinks_per_week) : "0");
  const [pregnant, setPregnant] = useState<boolean>(!!p.pregnant_or_breastfeeding);
  const [eating, setEating] = useState<boolean>(!!p.eating_disorder_history);
  const [glucoseMed, setGlucoseMed] = useState<boolean>(!!p.on_glucose_lowering_medicine);
  const [hearing, setHearing] = useState<boolean>(!!p.hearing_difficulty);
  const [questions, setQuestions] = useState<string[]>(p.doctor_questions ?? []);
  const [planner, setPlanner] = useState<boolean>(p.use_in_planner ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const toggle = (list: string[], set: (v: string[]) => void) => (c: string) => set(list.includes(c) ? list.filter((x) => x !== c) : [...list, c]);
  const opts = (codes: string[] = []) => codes.map((c) => ({ code: c, label: humanize(c) }));

  const save = async () => {
    setError("");
    if (!sex) { setError("Please pick a sex — it changes which ranges apply to you."); return; }
    setBusy(true);
    try {
      const saved = await api.saveHealthProfile({
        consent: true,
        date_of_birth: dob || null,
        sex,
        height_cm: height ? Number(height) : null,
        conditions,
        medicines,
        family_history: family,
        smoking,
        alcohol_drinks_per_week: alcohol ? Number(alcohol) : 0,
        pregnant_or_breastfeeding: sex === "male" ? false : pregnant,
        eating_disorder_history: eating,
        on_glucose_lowering_medicine: glucoseMed,
        hearing_difficulty: hearing,
        doctor_questions: questions,
        use_in_planner: planner,
      });
      onSaved(saved);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View testID="health-profile-form">
      <Text style={hs.label}>Date of birth</Text>
      <DateTimeField mode="date" value={dob} onChange={setDob} testID="health-dob" />
      <Text style={hs.label}>Sex</Text>
      <Chips options={SEX} value={[sex]} onToggle={setSex} testPrefix="health-sex" />
      <Text style={hs.label}>Height (cm)</Text>
      <TextInput style={hs.input} value={height} onChangeText={(v) => setHeight(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="e.g. 165" placeholderTextColor={colors.onSurfaceTertiary} testID="health-height" />

      <Text style={hs.label}>Anything a doctor has told you that you have?</Text>
      <Chips options={opts(options?.conditions)} value={conditions} onToggle={toggle(conditions, setConditions)} testPrefix="health-condition" />
      <Text style={hs.label}>Medicines you take (names only)</Text>
      <TagList value={medicines} onChange={setMedicines} placeholder="e.g. Metformin" testID="health-medicines" />
      <Text style={hs.label}>In your parents, brothers or sisters</Text>
      <Chips options={opts(options?.family_history)} value={family} onToggle={toggle(family, setFamily)} testPrefix="health-family" />

      <Text style={hs.label}>Do you smoke?</Text>
      <Chips options={SMOKING} value={[smoking]} onToggle={setSmoking} testPrefix="health-smoking" />
      <Text style={hs.label}>Alcoholic drinks in a usual week</Text>
      <TextInput style={hs.input} value={alcohol} onChangeText={(v) => setAlcohol(v.replace(/[^0-9]/g, ""))} keyboardType="number-pad" placeholder="0" placeholderTextColor={colors.onSurfaceTertiary} testID="health-alcohol" />

      <View style={{ marginTop: spacing.md }}>
        {sex !== "male" ? <Toggle label="Pregnant or breastfeeding" value={pregnant} onChange={setPregnant} testID="health-pregnant" /> : null}
        <Toggle label="Ever had an eating disorder" value={eating} onChange={setEating} testID="health-eating" />
        <Toggle label="On medicine that lowers blood sugar" value={glucoseMed} onChange={setGlucoseMed} testID="health-glucose-med" />
        <Toggle label="Some difficulty hearing" value={hearing} onChange={setHearing} testID="health-hearing" />
      </View>

      <Text style={hs.label}>Questions for your doctor</Text>
      <TagList value={questions} onChange={setQuestions} placeholder="Something you want to ask" testID="health-questions" />

      <View style={{ marginTop: spacing.md }}>
        <Toggle label="Let the planner use this when checking plans" value={planner} onChange={setPlanner} testID="health-use-in-planner" />
      </View>

      {error ? <Text style={[hs.error, { marginTop: spacing.md }]} testID="health-profile-error">{error}</Text> : null}
      <Pressable style={[hs.primary, { marginTop: spacing.xl }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="health-profile-save">
        {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>{saveLabel}</Text>}
      </Pressable>
    </View>
  );
}
