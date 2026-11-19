import { useCallback, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import DraftNote from "@/src/components/DraftNote";
import DateTimeField from "@/src/components/DateTimeField";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { todayIso } from "@/src/lib/habits";
import { colors, radius, spacing } from "@/src/lib/theme";

const ORDER = ["overdue", "never", "due_soon", "ok"];
const STATUS: Record<string, { label: string; color: string }> = {
  overdue: { label: "Overdue", color: colors.warning },
  never: { label: "Not done yet", color: colors.onSurfaceSecondary },
  due_soon: { label: "Due soon", color: colors.brandPrimary },
  ok: { label: "Up to date", color: colors.success },
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const niceDay = (iso?: string | null) => {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : String(iso);
};

export default function CheckupsScreen() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [doneFor, setDoneFor] = useState<any>(null);
  const [date, setDate] = useState(todayIso());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.getCheckups());
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your check-ups.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const markDone = async () => {
    setBusy(true);
    try {
      await api.markCheckupDone(doneFor.key, date);
      setDoneFor(null);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const checks: any[] = [...(data?.checks ?? [])].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const missing: string[] = data?.missing_profile ?? [];

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="checkups-screen">
      <HealthHeader title="Check-ups" testID="checkups" />
      <ScrollView contentContainerStyle={hs.scroll}>
        {!data ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
          <>
            {data.rules_reviewed === false ? <DraftNote /> : null}
            {error ? <Text style={hs.error}>{error}</Text> : null}
            {missing.length > 0 ? (
              <Pressable style={[hs.card, { flexDirection: "row", alignItems: "center", gap: spacing.sm }]} onPress={() => router.push("/life/health/settings" as any)} testID="checkups-missing-profile">
                <Text style={[hs.body, { flex: 1, color: colors.onSurface }]}>Add your date of birth and sex for a better list.</Text>
                <Text style={[hs.body, { color: colors.brandPrimary, fontWeight: "700" }]}>Add</Text>
              </Pressable>
            ) : null}
            {checks.map((c) => {
              const st = STATUS[c.status] ?? STATUS.never;
              return (
                <View key={c.key} style={hs.card} testID={`checkup-${c.key}`}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
                    <Text style={[hs.h, { flex: 1, fontSize: 16 }]}>{c.label}</Text>
                    <Text style={{ fontSize: 12, fontWeight: "700", color: st.color }} testID={`checkup-status-${c.key}`}>{st.label}</Text>
                  </View>
                  {c.ask_doctor ? (
                    <View style={{ alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary }}>
                      <Text style={{ fontSize: 12, fontWeight: "700", color: colors.onSurface }}>Ask your doctor</Text>
                    </View>
                  ) : null}
                  {c.why ? <Text style={hs.body}>{c.why}</Text> : null}
                  <Text style={hs.muted}>
                    {[c.last_done ? `Last done ${niceDay(c.last_done)}` : "Not recorded yet", c.next_due ? `Next due ${niceDay(c.next_due)}` : ""].filter(Boolean).join(" · ")}
                  </Text>
                  <Pressable style={[hs.chip, { alignSelf: "flex-start", minHeight: 36 }]} onPress={() => { setDate(todayIso()); setDoneFor(c); }} testID={`checkup-done-${c.key}`}>
                    <Text style={hs.chipText}>Done</Text>
                  </Pressable>
                </View>
              );
            })}
            {data.note ? <Text style={hs.muted}>{data.note}</Text> : null}
          </>
        )}
      </ScrollView>

      <Modal visible={!!doneFor} transparent animationType="slide" onRequestClose={() => setDoneFor(null)}>
        <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" }}>
          <Pressable style={{ flex: 1 }} onPress={() => setDoneFor(null)} />
          <View style={{ backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, gap: spacing.md }} testID="checkup-done-sheet">
            <Text style={hs.h}>When was your {String(doneFor?.label ?? "").toLowerCase()}?</Text>
            <DateTimeField mode="date" value={date} onChange={setDate} testID="checkup-done-date" />
            <Pressable style={[hs.primary, busy && { opacity: 0.5 }]} onPress={markDone} disabled={busy || !date} testID="checkup-done-save">
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
