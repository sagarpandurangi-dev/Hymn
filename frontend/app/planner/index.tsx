import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api, ApiError } from "@/src/lib/api";
import SimpleMarkdown from "@/src/components/planner/SimpleMarkdown";
import PlanPager from "@/src/components/planner/PlanPager";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

const CHAT_KEY = "hymn.planner.chatId";
type Turn = { role: "user" | "assistant"; text: string };

export default function PlannerScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const scrollRef = useRef<ScrollView>(null);
  const [chatId, setChatId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  /** Plans for this conversation: latest first, then the rest of plan_ids. */
  const loadPlans = useCallback(async (ids: string[], latest?: any) => {
    const order = latest?.id ? [latest.id, ...ids.filter((x) => x !== latest.id)] : ids;
    const got = await Promise.all(order.map((id) => (latest?.id === id ? Promise.resolve(latest) : api.getLifePlan(id).catch(() => null))));
    setPlans(got.filter(Boolean));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(CHAT_KEY);
        if (saved) {
          const h = await api.getPlanChat(saved);
          setChatId(saved);
          setTurns((h?.turns ?? []).map((t: any) => ({ role: t.role === "user" ? "user" : "assistant", text: String(t.text ?? "") })));
          await loadPlans(h?.plan_ids ?? []);
        }
      } catch {
        await AsyncStorage.removeItem(CHAT_KEY).catch(() => undefined);
      } finally {
        setLoading(false);
      }
    })();
  }, [loadPlans]);

  const send = async () => {
    const text = message.trim();
    if (!text || sending) return;
    setSending(true);
    setError("");
    setTurns((t) => [...t, { role: "user", text }]);
    try {
      const res = await api.planChat(chatId ? { message: text, chat_id: chatId } : { message: text });
      setMessage("");
      if (res?.chat_id) { setChatId(res.chat_id); AsyncStorage.setItem(CHAT_KEY, res.chat_id).catch(() => undefined); }
      setTurns((t) => [...t, { role: "assistant", text: String(res?.reply ?? "") }]);
      if (res?.latest_plan || res?.plan_ids?.length) await loadPlans(res.plan_ids ?? [], res.latest_plan);
    } catch (e) {
      const err = e as ApiError;
      setTurns((t) => t.slice(0, -1)); // keep the typed message in the box instead
      setError(err.status === 503 ? "The planner is unavailable right now." : err.message || "Couldn't send. Try again.");
    } finally {
      setSending(false);
    }
  };

  const newChat = async () => {
    await AsyncStorage.removeItem(CHAT_KEY).catch(() => undefined);
    setChatId(null);
    setTurns([]);
    setPlans([]);
    setError("");
  };

  const onPlanChanged = (p: any) => setPlans((list) => list.map((x) => (x.id === p.id ? p : x)));

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="planner-screen">
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/life" as any))} hitSlop={12} style={styles.iconBtn} testID="planner-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Planner</Text>
        <Pressable onPress={() => router.push("/planner/plans" as any)} hitSlop={8} style={styles.headBtn} testID="planner-my-plans">
          <Text style={styles.headBtnText}>My plans</Text>
        </Pressable>
        {turns.length > 0 ? (
          <Pressable onPress={newChat} hitSlop={8} style={styles.iconBtn} testID="planner-new-chat">
            <Ionicons name="create-outline" size={22} color={colors.onSurface} />
          </Pressable>
        ) : null}
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}>
          {loading ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : turns.length === 0 ? (
            <View style={styles.empty} testID="planner-empty">
              <Ionicons name="map-outline" size={28} color={colors.brandPrimary} />
              <Text style={styles.emptyTitle}>What do you want to make happen?</Text>
              <Text style={styles.emptyBody}>Tell me something like “Buy a car by March” or “Run a 10k in October”. I&apos;ll check your money, time and health and tell you if it fits.</Text>
            </View>
          ) : turns.map((t, i) => (
            <View key={i} style={[styles.bubble, t.role === "user" ? styles.userBubble : styles.botBubble]} testID={`planner-turn-${t.role}-${i}`}>
              {t.role === "user" ? <Text style={styles.userText}>{t.text}</Text> : <SimpleMarkdown text={t.text} />}
            </View>
          ))}
          {sending ? <View style={[styles.bubble, styles.botBubble]}><ActivityIndicator color={colors.onSurfaceTertiary} /></View> : null}
          {plans.length > 0 ? <PlanPager plans={plans} width={width - spacing.lg * 2} onChanged={onPlanChanged} /> : null}
        </ScrollView>

        {error ? <Text style={styles.error} testID="planner-error">{error}</Text> : null}
        <View style={styles.composer}>
          <TextInput
            style={styles.input}
            value={message}
            onChangeText={setMessage}
            placeholder="Describe a plan or answer the questions…"
            placeholderTextColor={colors.onSurfaceTertiary}
            multiline
            testID="planner-input"
          />
          <Pressable style={[styles.send, (!message.trim() || sending) && { opacity: 0.4 }]} onPress={send} disabled={!message.trim() || sending} testID="planner-send">
            <Ionicons name="arrow-up" size={20} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 24, fontWeight: "700", color: colors.onSurface },
  headBtn: { minHeight: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, justifyContent: "center" },
  headBtnText: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  scroll: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  empty: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxxl, paddingHorizontal: spacing.lg },
  emptyTitle: { fontSize: 18, fontWeight: "700", color: colors.onSurface, textAlign: "center" },
  emptyBody: { fontSize: 14, lineHeight: 20, color: colors.onSurfaceSecondary, textAlign: "center" },
  bubble: { borderRadius: radius.md, padding: spacing.md, maxWidth: "92%" },
  userBubble: { alignSelf: "flex-end", backgroundColor: colors.brandPrimary },
  botBubble: { alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary },
  userText: { fontSize: 15, lineHeight: 22, color: colors.onBrandPrimary },
  error: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xs, fontSize: 13, color: colors.error },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider, backgroundColor: colors.surface },
  input: { flex: 1, minHeight: 44, maxHeight: 140, borderRadius: radius.lg, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.lg, paddingTop: 12, paddingBottom: 12, fontSize: 15, color: colors.onSurface },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
});
