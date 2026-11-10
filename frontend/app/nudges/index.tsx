import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { api, ApiError, Nudge, NudgeSettings, NudgeSettingsUpdate } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import DateTimeField from "@/src/components/DateTimeField";
import { openNudgeScreen } from "@/src/lib/push";

type Draft = {
  daily_review: { enabled: boolean; time: string; adaptive: boolean };
  weekly_patterns: { enabled: boolean; weekday: number; time: string };
  reminders: { enabled: boolean };
  quiet_hours: { start: string; end: string };
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SECTIONS = ["daily_review", "weekly_patterns", "reminders", "quiet_hours"] as const;

const toDraft = (x: NudgeSettings): Draft => ({
  daily_review: {
    enabled: !!x.daily_review?.enabled,
    time: x.daily_review?.time || "",
    adaptive: !!x.daily_review?.adaptive,
  },
  weekly_patterns: {
    enabled: !!x.weekly_patterns?.enabled,
    weekday: x.weekly_patterns?.weekday ?? 6,
    time: x.weekly_patterns?.time || "",
  },
  reminders: { enabled: !!x.reminders?.enabled },
  quiet_hours: { start: x.quiet_hours?.start || "", end: x.quiet_hours?.end || "" },
});

/** Only the fields that differ from what was loaded. */
function changedFields(original: Draft, draft: Draft): Omit<NudgeSettingsUpdate, "timezone"> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const section of SECTIONS) {
    const before = original[section] as Record<string, unknown>;
    const after = draft[section] as Record<string, unknown>;
    for (const key of Object.keys(after)) {
      if (after[key] !== before[key]) {
        out[section] = { ...(out[section] || {}), [key]: after[key] };
      }
    }
  }
  return out;
}

const formatWhen = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

function ToggleRow({ label, value, onChange, testID }: { label: string; value: boolean; onChange: (v: boolean) => void; testID: string }) {
  return (
    <View style={styles.toggleRow}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: colors.borderStrong, true: colors.brandPrimary }}
        thumbColor={colors.surface}
        testID={testID}
      />
    </View>
  );
}

export default function NudgesScreen() {
  const router = useRouter();
  const [original, setOriginal] = useState<Draft | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [explanation, setExplanation] = useState("");
  const [nudges, setNudges] = useState<Nudge[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applySettings = (res: NudgeSettings) => {
    const d = toDraft(res);
    setOriginal(d);
    setDraft(d);
    setExplanation(res.daily_review_plan?.explanation || "");
  };

  const load = useCallback(async () => {
    setError("");
    try {
      const [settings, list] = await Promise.all([api.getNudgeSettings(), api.listNudges(20)]);
      const d = toDraft(settings);
      setOriginal(d);
      setDraft(d);
      setExplanation(settings.daily_review_plan?.explanation || "");
      setNudges(Array.isArray(list) ? list : ((list as any)?.nudges ?? (list as any)?.items ?? []));
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        setLoading(true);
        await load();
        if (alive) setLoading(false);
      })();
      return () => { alive = false; };
    }, [load]),
  );

  const update = <K extends keyof Draft>(section: K, patch: Partial<Draft[K]>) => {
    setNotice("");
    setDraft((prev) => (prev ? { ...prev, [section]: { ...prev[section], ...patch } } : prev));
  };

  const changes = original && draft ? changedFields(original, draft) : {};
  const dirty = Object.keys(changes).length > 0;

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setError("");
    try {
      const res = await api.updateNudgeSettings({
        ...changes,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      if (res && typeof res === "object" && "daily_review" in res) {
        applySettings(res);
      } else {
        setOriginal(draft);
      }
      setNotice("Saved.");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  const openNudge = async (n: Nudge) => {
    try {
      await api.markNudgeOpened(n.id);
    } catch (e) {
      setError((e as ApiError).message);
      return;
    }
    openNudgeScreen(router, n.data?.screen);
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="nudges-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Nudges</Text>
        <View style={{ width: 56 }} />
      </View>
      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={s.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.brandPrimary} />}
        >
          {draft ? (
            <>
              <Text style={s.label}>DAILY REVIEW</Text>
              <View style={styles.card}>
                <ToggleRow label="Daily review" value={draft.daily_review.enabled} onChange={(v) => update("daily_review", { enabled: v })} testID="nudges-daily-enabled" />
                <Text style={styles.fieldLabel}>Time</Text>
                <DateTimeField mode="time" value={draft.daily_review.time} onChange={(v) => update("daily_review", { time: v })} testID="nudges-daily-time" />
                <ToggleRow label="Learn my best time" value={draft.daily_review.adaptive} onChange={(v) => update("daily_review", { adaptive: v })} testID="nudges-daily-adaptive" />
                {explanation ? <Text style={styles.small} testID="nudges-daily-explanation">{explanation}</Text> : null}
              </View>

              <Text style={s.label}>WEEKLY SUMMARY</Text>
              <View style={styles.card}>
                <ToggleRow label="Weekly summary" value={draft.weekly_patterns.enabled} onChange={(v) => update("weekly_patterns", { enabled: v })} testID="nudges-weekly-enabled" />
                <Text style={styles.fieldLabel}>Day</Text>
                <View style={styles.weekdayRow}>
                  {WEEKDAYS.map((label, i) => {
                    const sel = draft.weekly_patterns.weekday === i;
                    return (
                      <Pressable
                        key={label}
                        onPress={() => update("weekly_patterns", { weekday: i })}
                        style={[styles.weekday, sel && s.chipSelected]}
                        testID={`nudges-weekday-${i}`}
                      >
                        <Text style={[s.chipText, sel && s.chipTextSelected]}>{label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
                <Text style={styles.fieldLabel}>Time</Text>
                <DateTimeField mode="time" value={draft.weekly_patterns.time} onChange={(v) => update("weekly_patterns", { time: v })} testID="nudges-weekly-time" />
              </View>

              <Text style={s.label}>REMINDERS</Text>
              <View style={styles.card}>
                <ToggleRow label="Reminders" value={draft.reminders.enabled} onChange={(v) => update("reminders", { enabled: v })} testID="nudges-reminders-enabled" />
              </View>

              <Text style={s.label}>QUIET HOURS</Text>
              <View style={[styles.card, { flexDirection: "row", gap: spacing.md }]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLabel}>Start</Text>
                  <DateTimeField mode="time" value={draft.quiet_hours.start} onChange={(v) => update("quiet_hours", { start: v })} testID="nudges-quiet-start" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLabel}>End</Text>
                  <DateTimeField mode="time" value={draft.quiet_hours.end} onChange={(v) => update("quiet_hours", { end: v })} testID="nudges-quiet-end" />
                </View>
              </View>

              {notice ? <Text style={styles.notice} testID="nudges-notice">{notice}</Text> : null}
              <Pressable
                style={[s.cta, { marginTop: spacing.lg }, (!dirty || saving) && s.ctaDisabled]}
                onPress={save}
                disabled={!dirty || saving}
                testID="nudges-save-button"
              >
                {saving ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Save</Text>}
              </Pressable>
            </>
          ) : null}

          {error ? <Text style={s.errorText} testID="nudges-error">{error}</Text> : null}

          <Text style={s.label}>RECENT NUDGES</Text>
          {nudges.length === 0 ? <Text style={styles.small}>No nudges yet.</Text> : null}
          <View style={{ gap: spacing.sm }}>
            {nudges.map((n) => (
              <Pressable
                key={n.id}
                style={({ pressed }) => [styles.card, pressed && { opacity: 0.8 }]}
                onPress={() => openNudge(n)}
                testID={`nudge-row-${n.id}`}
              >
                <View style={styles.nudgeHead}>
                  <Text style={styles.nudgeTitle}>{n.title}</Text>
                  <Text style={styles.small}>{formatWhen(n.sent_at || n.created_at)}</Text>
                </View>
                {n.body ? <Text style={styles.nudgeBody}>{n.body}</Text> : null}
              </Pressable>
            ))}
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  toggleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  toggleLabel: { fontSize: 15, color: colors.onSurface },
  fieldLabel: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  small: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 17 },
  notice: { fontSize: 13, color: colors.success, marginTop: spacing.md },
  weekdayRow: { flexDirection: "row", gap: spacing.xs },
  weekday: {
    flex: 1, height: 40, borderRadius: radius.pill, backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  nudgeHead: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: spacing.md },
  nudgeTitle: { flex: 1, fontSize: 15, fontWeight: "600", color: colors.onSurface },
  nudgeBody: { fontSize: 14, color: colors.onSurfaceSecondary },
});
