import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import WelcomeShell, { StepNav } from "./WelcomeShell";
import Chips from "./Chips";
import { api, ApiError } from "@/src/lib/api";
import { getSaved, markSaved } from "@/src/lib/welcome";
import { formStyles as fs } from "@/src/lib/formStyles";
import { colors, radius, spacing } from "@/src/lib/theme";

const RELATIONS = ["mother", "father", "spouse", "partner", "child", "sibling", "friend", "other"].map((r) => ({
  value: r, label: r[0].toUpperCase() + r.slice(1),
}));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS_IN = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

type Row = { name: string; relation: string; month: number | null; day: number | null; showBirthday: boolean };
const emptyRow = (): Row => ({ name: "", relation: "", month: null, day: null, showBirthday: false });
const pad = (n: number) => String(n).padStart(2, "0");

function PersonRow({ row, index, onChange }: { row: Row; index: number; onChange: (r: Row) => void }) {
  const maxDay = row.month ? DAYS_IN[row.month - 1] : 31;
  return (
    <View style={styles.card} testID={`welcome-person-${index}`}>
      <TextInput
        style={fs.input}
        value={row.name}
        onChangeText={(name) => onChange({ ...row, name })}
        placeholder="Name"
        placeholderTextColor={colors.onSurfaceTertiary}
        testID={`welcome-person-${index}-name`}
      />
      <Text style={fs.label}>Relation</Text>
      <Chips options={RELATIONS} selected={row.relation ? [row.relation] : []} onToggle={(relation) => onChange({ ...row, relation })} testID={`welcome-person-${index}-relation`} />
      {row.showBirthday ? (
        <>
          <Text style={fs.label}>Birthday (optional)</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={fs.chipRow}>
            {MONTHS.map((m, i) => (
              <Pressable key={m} onPress={() => onChange({ ...row, month: i + 1, day: row.day && row.day > DAYS_IN[i] ? null : row.day })} style={[fs.chip, row.month === i + 1 && fs.chipSelected]} testID={`welcome-person-${index}-month-${i + 1}`}>
                <Text style={[fs.chipText, row.month === i + 1 && fs.chipTextSelected]}>{m}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[fs.chipRow, { marginTop: spacing.sm }]}>
            {Array.from({ length: maxDay }, (_, i) => i + 1).map((d) => (
              <Pressable key={d} onPress={() => onChange({ ...row, day: d })} style={[fs.chip, { paddingHorizontal: spacing.md }, row.day === d && fs.chipSelected]} testID={`welcome-person-${index}-day-${d}`}>
                <Text style={[fs.chipText, row.day === d && fs.chipTextSelected]}>{d}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </>
      ) : (
        <Pressable onPress={() => onChange({ ...row, showBirthday: true })} style={styles.link} testID={`welcome-person-${index}-add-birthday`}>
          <Text style={styles.linkText}>+ Add birthday</Text>
        </Pressable>
      )}
    </View>
  );
}

export default function PeopleStep({ nav }: { nav: StepNav }) {
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [saved, setSaved] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      getSaved().then((s) => { if (s.includes("people")) setSaved(true); }),
      api.listPeople().then((p) => { if (Array.isArray(p) && p.length > 0) setSaved(true); }).catch(() => undefined),
    ]).finally(() => setChecking(false));
  }, []);

  const filled = rows.filter((r) => r.name.trim());

  const save = async () => {
    if (saved) { nav.next(); return; }
    if (filled.some((r) => !r.relation)) { setError("Pick how each person is related to you."); return; }
    if (filled.some((r) => (r.month === null) !== (r.day === null))) { setError("Pick both a day and a month for the birthday, or neither."); return; }
    setBusy(true);
    setError("");
    try {
      const done = await getSaved();
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        if (!r.name.trim() || done.includes(`person:${i}`)) continue;
        await api.createPerson({
          name: r.name.trim(),
          relation: r.relation,
          circle: "inner",
          birthday: r.month && r.day ? `${pad(r.month)}-${pad(r.day)}` : null,
        });
        await markSaved(`person:${i}`);
      }
      await markSaved("people");
      nav.next();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const update = (i: number, r: Row) => { setError(""); setRows(rows.map((x, j) => (j === i ? r : x))); };

  return (
    <WelcomeShell nav={nav} title="People who matter" subtitle="Up to 3. Hymn remembers birthdays and nudges you to stay in touch." primaryLabel="Continue" onPrimary={save} primaryDisabled={checking || (!saved && filled.length === 0)} busy={busy} error={error}>
      {saved ? (
        <Text style={{ fontSize: 13, color: colors.onSurfaceSecondary }} testID="welcome-already-saved">Already saved. You can add more later.</Text>
      ) : (
        <View style={{ gap: spacing.lg }}>
          {rows.map((r, i) => <PersonRow key={i} row={r} index={i} onChange={(nr) => update(i, nr)} />)}
          {rows.length < 3 ? (
            <Pressable onPress={() => setRows([...rows, emptyRow()])} style={styles.link} testID="welcome-person-add">
              <Text style={styles.linkText}>+ Add another person</Text>
            </Pressable>
          ) : null}
        </View>
      )}
    </WelcomeShell>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  link: { minHeight: 44, justifyContent: "center", marginTop: spacing.xs },
  linkText: { fontSize: 15, fontWeight: "600", color: colors.brandPrimary },
});
