import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import WelcomeShell, { StepNav } from "./WelcomeShell";
import Chips from "./Chips";
import DateTimeField from "@/src/components/DateTimeField";
import { api, ApiError } from "@/src/lib/api";
import { getSaved, markSaved, todayISO, WEEK_DAYS, WEEK_DAY_SHORT } from "@/src/lib/welcome";
import { formStyles as fs } from "@/src/lib/formStyles";
import { colors, spacing } from "@/src/lib/theme";

const WORK_TYPES = [
  { value: "salaried", label: "Salaried" },
  { value: "self_employed", label: "Self-employed" },
  { value: "business_owner", label: "Business owner" },
  { value: "freelancer", label: "Freelancer" },
  { value: "articleship", label: "Articleship / intern" },
  { value: "looking_for_work", label: "Looking for work" },
  { value: "homemaker", label: "Homemaker" },
  { value: "not_now", label: "Not now" },
];
const SCHEDULED = ["salaried", "self_employed", "business_owner", "freelancer", "articleship"];
const COMMUTES = [0, 15, 30, 45, 60, 90].map((m) => ({ value: String(m), label: m === 0 ? "None" : `${m} min` }));
const DAY_OPTIONS = WEEK_DAYS.map((d) => ({ value: d, label: WEEK_DAY_SHORT[d] }));

const SavedNote = () => (
  <Text style={{ fontSize: 13, color: colors.onSurfaceSecondary }} testID="welcome-already-saved">
    Already saved. You can change this later.
  </Text>
);

export function WorkStep({ nav }: { nav: StepNav }) {
  const [type, setType] = useState("");
  const [days, setDays] = useState<string[]>(["monday", "tuesday", "wednesday", "thursday", "friday"]);
  const [start, setStart] = useState("09:30");
  const [end, setEnd] = useState("18:30");
  const [commute, setCommute] = useState("0");
  const [saved, setSaved] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Already saved here, or the server already has a work role (e.g. another device).
  useEffect(() => {
    Promise.all([
      getSaved().then((s) => { if (s.includes("work")) setSaved(true); }),
      api.listWorkRoles().then((r) => { if (Array.isArray(r) && r.length > 0) setSaved(true); }).catch(() => undefined),
    ]).finally(() => setChecking(false));
  }, []);

  const scheduled = SCHEDULED.includes(type);

  const save = async () => {
    if (saved || type === "not_now") { nav.next(); return; }
    if (scheduled) {
      if (days.length === 0) { setError("Pick at least one work day."); return; }
      if (!start || !end) { setError("Add a start and end time."); return; }
    }
    setBusy(true);
    setError("");
    try {
      await api.createWorkRole(
        scheduled
          ? { type, work_days: WEEK_DAYS.filter((d) => days.includes(d)), start_time: start, end_time: end, commute_minutes: Number(commute) }
          : { type },
      );
      await markSaved("work");
      nav.next();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save your work.");
    } finally {
      setBusy(false);
    }
  };

  const toggleDay = (d: string) => setDays(days.includes(d) ? days.filter((x) => x !== d) : [...days, d]);

  return (
    <WelcomeShell nav={nav} title="Do you work?" primaryLabel="Continue" onPrimary={save} primaryDisabled={checking || (!saved && !type)} busy={busy} error={error}>
      {saved ? <SavedNote /> : (
        <>
          <Chips options={WORK_TYPES} selected={type ? [type] : []} onToggle={(v) => { setType(v); setError(""); }} testID="welcome-work-type" />
          {scheduled ? (
            <View>
              <Text style={fs.label}>Work days</Text>
              <Chips options={DAY_OPTIONS} selected={days} onToggle={toggleDay} testID="welcome-work-days" />
              <View style={{ flexDirection: "row", gap: spacing.md }}>
                <View style={{ flex: 1 }}>
                  <Text style={fs.label}>Start</Text>
                  <DateTimeField mode="time" value={start} onChange={setStart} testID="welcome-work-start" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={fs.label}>End</Text>
                  <DateTimeField mode="time" value={end} onChange={setEnd} testID="welcome-work-end" />
                </View>
              </View>
              <Text style={fs.label}>Commute each way</Text>
              <Chips options={COMMUTES} selected={[commute]} onToggle={setCommute} testID="welcome-work-commute" />
            </View>
          ) : null}
        </>
      )}
    </WelcomeShell>
  );
}

export function SleepStep({ nav }: { nav: StepNav }) {
  const [bed, setBed] = useState("23:00");
  const [wake, setWake] = useState("07:00");
  const [savedDays, setSavedDays] = useState<string[]>([]);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Days already covered locally or by sleep blocks on the server.
  useEffect(() => {
    Promise.all([
      getSaved().then((s) => s.filter((k) => k.startsWith("sleep:")).map((k) => k.slice(6))),
      api.listTimeCommitments()
        .then((list) => list.filter((c) => c.commitment_type === "sleep").map((c) => c.day_of_week))
        .catch(() => [] as string[]),
    ]).then(([a, b]) => setSavedDays(Array.from(new Set([...a, ...b])))).finally(() => setChecking(false));
  }, []);

  const allSaved = WEEK_DAYS.every((d) => savedDays.includes(d));

  const save = async () => {
    if (allSaved) { nav.next(); return; }
    if (!bed || !wake) { setError("Add a bedtime and a wake-up time."); return; }
    if (bed === wake) { setError("Bedtime and wake-up can't be the same."); return; }
    setBusy(true);
    setError("");
    const effective = todayISO();
    const done = [...savedDays];
    try {
      // One block per day; overnight (e.g. 23:00 → 07:00) is a single entry.
      for (const day of WEEK_DAYS) {
        if (done.includes(day)) continue;
        await api.createTimeCommitment({
          title: "Sleep", day_of_week: day, start_time: bed, end_time: wake,
          commitment_type: "sleep", flexibility: "fixed", effective_from: effective,
        });
        await markSaved(`sleep:${day}`);
        done.push(day);
      }
      setSavedDays(done);
      nav.next();
    } catch (e) {
      setSavedDays(done);
      setError((e as ApiError).message || "Couldn't save your sleep.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <WelcomeShell nav={nav} title="When do you sleep?" subtitle="Hymn keeps this time free for rest." primaryLabel="Continue" onPrimary={save} primaryDisabled={checking} busy={busy} error={error}>
      {allSaved ? <SavedNote /> : (
        <View style={{ flexDirection: "row", gap: spacing.md }}>
          <View style={{ flex: 1 }}>
            <Text style={fs.label}>Bedtime</Text>
            <DateTimeField mode="time" value={bed} onChange={setBed} testID="welcome-sleep-bed" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={fs.label}>Wake-up</Text>
            <DateTimeField mode="time" value={wake} onChange={setWake} testID="welcome-sleep-wake" />
          </View>
        </View>
      )}
    </WelcomeShell>
  );
}
