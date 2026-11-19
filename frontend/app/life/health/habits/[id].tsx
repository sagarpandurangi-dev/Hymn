import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs, PhoneText } from "@/src/components/health/ui";
import { freedLine, progressLine, reasonOf, todayIso, topTriggers, TRIGGERS, triggerLabel } from "@/src/lib/habits";
import { formatINR } from "@/src/lib/finance/format";
import { showToast } from "@/src/lib/toast";
import { colors, radius, spacing } from "@/src/lib/theme";

const confirmDelete = (ok: () => void) => {
  const body = "Stop tracking this habit? Your logs for it will be removed.";
  if (Platform.OS === "web") { if (window.confirm(body)) ok(); return; }
  Alert.alert("Delete habit", body, [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: ok }]);
};

function TriggerChips({ value, onToggle, testPrefix }: { value: string[]; onToggle: (c: string) => void; testPrefix: string }) {
  return (
    <View style={hs.chipRow}>
      {TRIGGERS.map((t) => {
        const on = value.includes(t.code);
        return (
          <Pressable key={t.code} style={[hs.chip, on && hs.chipOn]} onPress={() => onToggle(t.code)} testID={`${testPrefix}-${t.code}`}>
            <Text style={[hs.chipText, on && hs.chipTextOn]}>{t.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function HabitScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [h, setH] = useState<any>(null);
  const [error, setError] = useState("");
  // Urge
  const [urgeOpen, setUrgeOpen] = useState(false);
  const [urgeTrigger, setUrgeTrigger] = useState("");
  const [urge, setUrge] = useState<any>(null);
  const [urgeBusy, setUrgeBusy] = useState(false);
  // Daily check-in
  const [amount, setAmount] = useState("");
  const [triggers, setTriggers] = useState<string[]>([]);
  const [logBusy, setLogBusy] = useState(false);
  const [logMsg, setLogMsg] = useState("");
  const [dream, setDream] = useState<any>(null);
  const [dreamBusy, setDreamBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setH(await api.getHabit(String(id)));
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load this habit.");
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const sendUrge = async () => {
    setUrgeBusy(true);
    setError("");
    try {
      setUrge(await api.habitUrge(String(id), urgeTrigger ? { date: todayIso(), trigger: urgeTrigger } : { date: todayIso() }));
    } catch (e) {
      setError((e as ApiError).message || "Couldn't reach Hymn. Take a slow breath — this will pass.");
    } finally {
      setUrgeBusy(false);
    }
  };

  const sendLog = async () => {
    if (amount === "") { setLogMsg("Enter how much — 0 is a clean day."); return; }
    setLogBusy(true);
    setLogMsg("");
    try {
      const res = await api.logHabit(String(id), { date: todayIso(), amount: Number(amount), triggers });
      if (res?.id) setH(res); else await load();
      setLogMsg(Number(amount) === 0 ? "A clean day — well done." : "Logged. Thanks for being honest with yourself.");
      setAmount("");
      setTriggers([]);
    } catch (e) {
      setLogMsg((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setLogBusy(false);
    }
  };

  const sendToDream = async () => {
    setDreamBusy(true);
    setError("");
    try {
      setDream(await api.habitDreamFund(String(id)));
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't set that up. Try again.");
    } finally {
      setDreamBusy(false);
    }
  };

  const remove = () => confirmDelete(async () => {
    try {
      await api.deleteHabit(String(id));
      showToast("Habit removed.");
      if (router.canGoBack()) router.back(); else router.replace("/life/health/habits" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete. Try again.");
    }
  });

  if (!h) {
    return (
      <SafeAreaView style={hs.safe} edges={["top", "bottom"]}>
        <HealthHeader title="Habit" testID="habit" />
        <View style={{ padding: spacing.lg }}>{error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />}</View>
      </SafeAreaView>
    );
  }

  const p = h.progress ?? {};
  const freed = freedLine(p);
  const tops = topTriggers(p.top_triggers);
  const tips: string[] = p.steady_the_edge ?? [];
  const canDream = Number(h.cost_per_unit) > 0 && !!h.serves_plan_id;

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="habit-screen">
      <HealthHeader title={h.label} testID="habit" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          {p.welcome_back ? (
            <View style={[hs.card, { backgroundColor: colors.brandTertiary }]} testID="habit-welcome-back">
              <Text style={[hs.body, { color: colors.onSurface, fontSize: 16 }]}>{p.welcome_back}</Text>
            </View>
          ) : null}
          {reasonOf(h) ? <Text style={[hs.body, { color: colors.onSurface, fontSize: 16 }]}>For: {reasonOf(h)}</Text> : null}

          {/* Urge */}
          {urge ? (
            <View style={[hs.card, { gap: spacing.md }]} testID="habit-urge-result">
              <Text style={hs.muted}>Remember why</Text>
              <Text style={{ fontSize: 26, lineHeight: 34, fontWeight: "700", color: colors.onSurface }} testID="habit-your-reason">{urge.your_reason ?? reasonOf(h)}</Text>
              {(urge.try_this ?? []).length > 0 ? (
                <View style={{ gap: spacing.sm }}>
                  <Text style={hs.section}>TRY THIS</Text>
                  {urge.try_this.map((t: string, i: number) => (
                    <View key={i} style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Ionicons name="checkmark-circle-outline" size={20} color={colors.brandPrimary} />
                      <Text style={[hs.body, { flex: 1, color: colors.onSurface, fontSize: 16 }]}>{t}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
              {urge.note ? <Text style={hs.body}>{urge.note}</Text> : null}
              <Pressable style={hs.secondary} onPress={() => { setUrge(null); setUrgeOpen(false); setUrgeTrigger(""); }} testID="habit-urge-done">
                <Text style={hs.secondaryText}>It passed</Text>
              </Pressable>
            </View>
          ) : urgeOpen ? (
            <View style={hs.card} testID="habit-urge-sheet">
              <Text style={hs.h}>What&apos;s going on? (optional)</Text>
              <TriggerChips value={[urgeTrigger]} onToggle={(c) => setUrgeTrigger(urgeTrigger === c ? "" : c)} testPrefix="habit-urge-trigger" />
              <Pressable style={[hs.primary, { marginTop: spacing.sm }, urgeBusy && { opacity: 0.5 }]} onPress={sendUrge} disabled={urgeBusy} testID="habit-urge-send">
                {urgeBusy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Help me through it</Text>}
              </Pressable>
            </View>
          ) : (
            <Pressable style={{ minHeight: 88, borderRadius: radius.lg, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center", gap: 4 }} onPress={() => setUrgeOpen(true)} testID="habit-urge">
              <Ionicons name="hand-left-outline" size={26} color={colors.onBrandPrimary} />
              <Text style={{ color: colors.onBrandPrimary, fontSize: 19, fontWeight: "700" }}>I&apos;m having an urge</Text>
            </Pressable>
          )}

          {/* Progress */}
          <View style={hs.card} testID="habit-progress">
            <Text style={[hs.h, { fontSize: 16 }]}>{progressLine(p)}</Text>
            {freed ? <Text style={[hs.body, { color: colors.success, fontWeight: "600" }]}>{freed}</Text> : null}
            {tops.length > 0 ? <Text style={hs.body}>Most often around: {tops.map((t) => triggerLabel(t.code).toLowerCase()).join(", ")}</Text> : null}
          </View>

          {/* Daily check-in */}
          <View style={hs.card} testID="habit-checkin">
            <Text style={hs.h}>Today&apos;s check-in</Text>
            <Text style={hs.label}>How much today? ({h.unit})</Text>
            <TextInput style={hs.input} value={amount} onChangeText={(v) => setAmount(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="0 = a clean day" placeholderTextColor={colors.onSurfaceTertiary} testID="habit-log-amount" />
            <Text style={hs.label}>Anything that set it off?</Text>
            <TriggerChips value={triggers} onToggle={(c) => setTriggers(triggers.includes(c) ? triggers.filter((x) => x !== c) : [...triggers, c])} testPrefix="habit-log-trigger" />
            {logMsg ? <Text style={[hs.body, { color: colors.onSurface }]} testID="habit-log-message">{logMsg}</Text> : null}
            <Pressable style={[hs.primary, { marginTop: spacing.sm }, logBusy && { opacity: 0.5 }]} onPress={sendLog} disabled={logBusy} testID="habit-log-save">
              {logBusy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save today</Text>}
            </Pressable>
          </View>

          {tips.length > 0 ? (
            <View style={hs.card} testID="habit-steady-tips">
              <Text style={hs.h}>Steady the edge</Text>
              {tips.map((t, i) => <Text key={i} style={hs.body}>• {t}</Text>)}
            </View>
          ) : null}

          {canDream ? (
            dream || h.dream_fund_id ? (
              <View style={hs.card} testID="habit-dream-set">
                <Text style={[hs.body, { color: colors.onSurface }]}>
                  {dream ? `${formatINR(dream.monthly)} a month now goes to ${dream.goes_to}.` : "What you save goes to your dream."}
                </Text>
              </View>
            ) : (
              <Pressable style={[hs.secondary, dreamBusy && { opacity: 0.5 }]} onPress={sendToDream} disabled={dreamBusy} testID="habit-dream-fund">
                {dreamBusy ? <ActivityIndicator color={colors.onSurface} /> : <><Ionicons name="sparkles-outline" size={18} color={colors.onSurface} /><Text style={hs.secondaryText}>Send what I save to my dream</Text></>}
              </Pressable>
            )
          ) : null}

          {h.support ? (
            <View style={hs.card} testID="habit-support">
              <Text style={hs.section}>SUPPORT</Text>
              <PhoneText text={h.support} style={[hs.body, { color: colors.onSurface }]} />
            </View>
          ) : null}

          {error ? <Text style={hs.error}>{error}</Text> : null}
          <Pressable style={{ minHeight: 48, alignItems: "center", justifyContent: "center" }} onPress={remove} testID="habit-delete">
            <Text style={[hs.body, { color: colors.error, fontWeight: "600" }]}>Delete this habit</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
