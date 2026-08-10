import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Proposal = {
  summary?: string;
  feasibility_note?: string;
  expected_outcomes?: { title: string; target_value?: string; unit?: string; deadline?: string; outcome_type?: string }[];
  tasks?: { title: string; expected_outcome_title?: string; due_date?: string; priority?: string; commitment_type?: string; notes?: string }[];
  checkins?: { type: string; title: string; date: string; time: string; expected_outcome_title?: string; project_id?: string; notes?: string }[];
  checkin_recurrences?: {
    type: string; title: string; start_date: string; end_date: string;
    days_of_week?: string[]; time: string; expected_outcome_title?: string; project_id?: string; notes?: string;
  }[];
  existing_item_updates?: {
    kind: "goal" | "project" | "task"; id: string;
    patch: Record<string, string>;
  }[];
  consolidations?: {
    kind: "goal" | "project"; candidate_ids: string[]; reason?: string;
  }[];
  time_commitments?: {
    title: string; day_of_week: string; start_time: string; end_time: string;
    commitment_type?: string; flexibility?: string; notes?: string;
  }[];
  existing_item_changes?: {
    kind: "goal" | "project" | "task"; id: string;
    action: "postpone" | "cancel"; new_due_date?: string; reason?: string;
  }[];
  checkin_cadence?: string;
  target_updates?: { deadline?: string; notes?: string; commitment_type?: string };
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  proposal?: Proposal | null;
  materialized_at?: string | null;
  materialized_summary?: string | null;
};

type Conversation = {
  id: string;
  target_type: "goal" | "project";
  target_id: string;
  messages: Message[];
};

const OPENER_HINTS = [
  "Help me break this down into weekly milestones.",
  "What am I missing to make this feasible?",
  "Suggest 5 concrete next tasks.",
  "How should I sequence this over the next 3 months?",
];

export default function PlanningChatScreen() {
  const { targetType, targetId } = useLocalSearchParams<{ targetType: string; targetId: string }>();
  const router = useRouter();
  const scrollRef = useRef<ScrollView | null>(null);

  const [conv, setConv] = useState<Conversation | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [targetTitle, setTargetTitle] = useState<string>("");

  const tt = (targetType === "goal" || targetType === "project") ? targetType : "goal";

  const load = useCallback(async () => {
    if (!targetId) return;
    setLoading(true);
    setError(null);
    try {
      const [t, c] = await Promise.all([
        tt === "goal" ? api.getGoal(targetId).catch(() => null) : api.getProject(targetId).catch(() => null),
        api.planningGetConversation(tt, targetId),
      ]);
      if (t) setTargetTitle((t as any).title || "");
      setConv(c as Conversation);
    } catch (e: any) {
      setError(e?.message || "Could not load the conversation.");
    } finally {
      setLoading(false);
    }
  }, [targetId, tt]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    // Scroll to bottom whenever conversation grows.
    const tid = setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 60);
    return () => clearTimeout(tid);
  }, [conv?.messages.length, sending]);

  const send = useCallback(async (text: string) => {
    if (!targetId || !text.trim() || sending) return;
    setSending(true);
    setError(null);
    // Optimistic user bubble.
    const tempUser: Message = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text.trim(),
      created_at: new Date().toISOString(),
    };
    setConv((prev) => (prev ? { ...prev, messages: [...prev.messages, tempUser] } : prev));
    setInput("");
    try {
      const next = await api.planningSendMessage(tt, targetId, text.trim());
      setConv(next as Conversation);
    } catch (e: any) {
      setError(e?.message || "The assistant couldn't reply. Please try again.");
      // Roll back optimistic bubble on error.
      setConv((prev) =>
        prev ? { ...prev, messages: prev.messages.filter((m) => m.id !== tempUser.id) } : prev,
      );
    } finally {
      setSending(false);
    }
  }, [targetId, tt, sending]);

  const apply = useCallback(async (msg: Message) => {
    if (!conv) return;
    setApplyingId(msg.id);
    setError(null);
    try {
      const res = await api.planningMaterialize(conv.id, msg.id);
      setConv(res.conversation as Conversation);
    } catch (e: any) {
      setError(e?.message || "Could not apply changes.");
    } finally {
      setApplyingId(null);
    }
  }, [conv]);

  const reset = useCallback(async () => {
    if (!targetId) return;
    setSending(true);
    try {
      const next = await api.planningReset(tt, targetId);
      setConv(next as Conversation);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Could not reset the conversation.");
    } finally {
      setSending(false);
    }
  }, [targetId, tt]);

  const showOpeners = useMemo(
    () => !loading && conv && conv.messages.length === 0 && !sending,
    [loading, conv, sending],
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <View style={styles.headerRow}>
          <Pressable onPress={() => router.back()} testID="planning-back" hitSlop={12}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, marginLeft: spacing.sm }}>
            <Text style={styles.headerLabel}>PLAN WITH HYMN</Text>
            <Text style={styles.headerTitle} numberOfLines={1}>{targetTitle || "…"}</Text>
          </View>
          <Pressable onPress={reset} testID="planning-reset" hitSlop={12} disabled={sending}>
            <Ionicons name="refresh" size={20} color={colors.onSurfaceSecondary} />
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
        ) : (
          <ScrollView
            ref={scrollRef}
            contentContainerStyle={styles.messagesContainer}
            keyboardShouldPersistTaps="handled"
          >
            {(conv?.messages.length ?? 0) === 0 && (
              <View style={styles.welcomeCard}>
                <Ionicons name="sparkles" size={22} color={colors.brandPrimary} />
                <Text style={styles.welcomeTitle}>Let's plan this together.</Text>
                <Text style={styles.welcomeBody}>
                  Tell me what you want to accomplish, what's already tried, or what's blocking
                  you. I can propose outcomes, tasks and cadences and apply them straight to
                  {tt === "goal" ? " this Goal" : " this Project"}.
                </Text>
              </View>
            )}

            {conv?.messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onApply={apply}
                applying={applyingId === m.id}
              />
            ))}

            {sending && (
              <View style={[styles.bubble, styles.assistantBubble]}>
                <ActivityIndicator size="small" color={colors.brandPrimary} />
                <Text style={styles.thinkingText}>Hymn is thinking…</Text>
              </View>
            )}
          </ScrollView>
        )}

        {error ? (
          <View style={styles.errorBanner}>
            <Ionicons name="alert-circle-outline" size={16} color={colors.error} />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {showOpeners ? (
          <View style={styles.openersRow}>
            {OPENER_HINTS.map((h) => (
              <Pressable key={h} onPress={() => send(h)} style={styles.opener} testID={`planning-opener-${h.slice(0, 12)}`}>
                <Text style={styles.openerText}>{h}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        <View style={styles.inputRow}>
          <TextInput
            value={input}
            onChangeText={setInput}
            placeholder="Message Hymn…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
            multiline
            editable={!sending}
            testID="planning-input"
            onSubmitEditing={() => send(input)}
            blurOnSubmit={false}
          />
          <Pressable
            onPress={() => send(input)}
            style={[styles.sendBtn, (!input.trim() || sending) && { opacity: 0.4 }]}
            disabled={!input.trim() || sending}
            testID="planning-send"
          >
            <Ionicons name="arrow-up" size={20} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function MessageBubble({
  message, onApply, applying,
}: {
  message: Message;
  onApply: (m: Message) => void;
  applying: boolean;
}) {
  const isUser = message.role === "user";
  const proposal = message.proposal;
  const applied = !!message.materialized_at;
  return (
    <View style={{ marginVertical: spacing.xs, alignItems: isUser ? "flex-end" : "flex-start" }}>
      <View style={[styles.bubble, isUser ? styles.userBubble : styles.assistantBubble]}>
        <Text style={isUser ? styles.userText : styles.assistantText}>{message.content}</Text>
      </View>
      {!isUser && proposal ? (
        <View style={styles.proposalCard} testID={`planning-proposal-${message.id}`}>
          <View style={styles.proposalHeader}>
            <Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} />
            <Text style={styles.proposalTitle}>Proposed changes</Text>
          </View>
          {proposal.summary ? <Text style={styles.proposalSummary}>{proposal.summary}</Text> : null}
          {proposal.feasibility_note ? (
            <View style={styles.feasibilityNote}>
              <Ionicons name="warning-outline" size={14} color={colors.warning} />
              <Text style={styles.feasibilityText}>{proposal.feasibility_note}</Text>
            </View>
          ) : null}
          {proposal.expected_outcomes && proposal.expected_outcomes.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>
                {proposal.expected_outcomes.length} outcome{proposal.expected_outcomes.length !== 1 ? "s" : ""}
              </Text>
              {proposal.expected_outcomes.slice(0, 6).map((e, i) => (
                <Text key={i} style={styles.proposalItem}>• {e.title}</Text>
              ))}
              {proposal.expected_outcomes.length > 6 ? (
                <Text style={styles.proposalMore}>+ {proposal.expected_outcomes.length - 6} more</Text>
              ) : null}
            </View>
          ) : null}
          {proposal.tasks && proposal.tasks.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>
                {proposal.tasks.length} task{proposal.tasks.length !== 1 ? "s" : ""}
              </Text>
              {proposal.tasks.slice(0, 8).map((t, i) => (
                <Text key={i} style={styles.proposalItem}>
                  • {t.title}{t.due_date ? `  (${t.due_date})` : ""}
                  {t.commitment_type === "exclusive" ? "  🔒" : ""}
                </Text>
              ))}
              {proposal.tasks.length > 8 ? (
                <Text style={styles.proposalMore}>+ {proposal.tasks.length - 8} more</Text>
              ) : null}
            </View>
          ) : null}
          {proposal.time_commitments && proposal.time_commitments.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>
                {proposal.time_commitments.length} life pattern{proposal.time_commitments.length !== 1 ? "s" : ""}
              </Text>
              {proposal.time_commitments.map((tc, i) => (
                <Text key={i} style={styles.proposalItem}>
                  • {tc.title} · {tc.day_of_week} {tc.start_time}–{tc.end_time}
                </Text>
              ))}
            </View>
          ) : null}
          {proposal.existing_item_changes && proposal.existing_item_changes.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>Trade-offs</Text>
              {proposal.existing_item_changes.map((c, i) => (
                <View key={i} style={styles.tradeoffRow}>
                  <View
                    style={[
                      styles.tradeoffBadge,
                      c.action === "cancel" ? { backgroundColor: colors.error + "22" } : { backgroundColor: colors.warning + "22" },
                    ]}
                  >
                    <Text
                      style={[
                        styles.tradeoffBadgeText,
                        { color: c.action === "cancel" ? colors.error : colors.warning },
                      ]}
                    >
                      {c.action === "cancel" ? "CANCEL" : "POSTPONE"}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.proposalItem} numberOfLines={2}>
                      {c.kind} · {c.reason || "trade-off"}
                      {c.action === "postpone" && c.new_due_date ? ` → ${c.new_due_date}` : ""}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          ) : null}
          {proposal.checkins && proposal.checkins.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>
                {proposal.checkins.length} check-in{proposal.checkins.length !== 1 ? "s" : ""}
              </Text>
              {proposal.checkins.slice(0, 6).map((c, i) => (
                <Text key={i} style={styles.proposalItem}>• {c.title}  ({c.date} {c.time})</Text>
              ))}
              {proposal.checkins.length > 6 ? (
                <Text style={styles.proposalMore}>+ {proposal.checkins.length - 6} more</Text>
              ) : null}
            </View>
          ) : null}
          {proposal.checkin_recurrences && proposal.checkin_recurrences.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>Recurring check-ins</Text>
              {proposal.checkin_recurrences.map((r, i) => (
                <Text key={i} style={styles.proposalItem}>
                  • {r.title} · {r.start_date} → {r.end_date} at {r.time}
                  {r.days_of_week && r.days_of_week.length > 0 && r.days_of_week.length < 7
                    ? `  (${r.days_of_week.map((d) => d.slice(0, 3)).join(", ")})`
                    : "  (every day)"}
                </Text>
              ))}
            </View>
          ) : null}
          {proposal.existing_item_updates && proposal.existing_item_updates.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>
                {proposal.existing_item_updates.length} update{proposal.existing_item_updates.length !== 1 ? "s" : ""}
              </Text>
              {proposal.existing_item_updates.map((u, i) => (
                <Text key={i} style={styles.proposalItem}>
                  • {u.kind}: {Object.keys(u.patch).join(", ")}
                </Text>
              ))}
            </View>
          ) : null}
          {proposal.consolidations && proposal.consolidations.length > 0 ? (
            <View style={styles.proposalSection}>
              <Text style={styles.proposalSectionLabel}>Consolidations</Text>
              {proposal.consolidations.map((c, i) => (
                <View key={i} style={styles.tradeoffRow}>
                  <View style={[styles.tradeoffBadge, { backgroundColor: colors.brandPrimary + "22" }]}>
                    <Text style={[styles.tradeoffBadgeText, { color: colors.brandPrimary }]}>MERGE</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.proposalItem} numberOfLines={3}>
                      {c.candidate_ids.length} {c.kind}s: {c.reason || "duplicate detected"}
                    </Text>
                    <Text style={styles.proposalMore}>Hymn will keep the richest and merge the rest.</Text>
                  </View>
                </View>
              ))}
            </View>
          ) : null}
          {proposal.checkin_cadence ? (
            <Text style={styles.proposalItem}>Cadence → {proposal.checkin_cadence}</Text>
          ) : null}
          {applied ? (
            <View style={styles.appliedRow}>
              <Ionicons name="checkmark-circle" size={16} color={colors.success} />
              <Text style={styles.appliedText}>{message.materialized_summary || "Applied."}</Text>
            </View>
          ) : (
            <Pressable
              onPress={() => onApply(message)}
              disabled={applying}
              style={[styles.applyBtn, applying && { opacity: 0.5 }]}
              testID={`planning-apply-${message.id}`}
            >
              {applying ? (
                <ActivityIndicator size="small" color={colors.onBrandPrimary} />
              ) : (
                <>
                  <Ionicons name="checkmark" size={16} color={colors.onBrandPrimary} />
                  <Text style={styles.applyBtnText}>Apply these changes</Text>
                </>
              )}
            </Pressable>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  headerRow: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderStrong,
  },
  headerLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: colors.onSurface, fontWeight: "600" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  messagesContainer: { padding: spacing.lg, paddingBottom: spacing.xl },
  welcomeCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg, gap: spacing.sm, marginBottom: spacing.md,
  },
  welcomeTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600" },
  welcomeBody: { fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  bubble: {
    maxWidth: "88%", padding: spacing.md,
    borderRadius: radius.md, flexDirection: "row", alignItems: "flex-start", gap: 8,
  },
  userBubble: {
    backgroundColor: colors.brandPrimary,
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: colors.surfaceSecondary,
    borderBottomLeftRadius: 4,
  },
  userText: { color: colors.onBrandPrimary, fontSize: 15, lineHeight: 21 },
  assistantText: { color: colors.onSurface, fontSize: 15, lineHeight: 21 },
  thinkingText: { color: colors.onSurfaceSecondary, fontSize: 13, marginLeft: 6 },
  proposalCard: {
    marginTop: spacing.sm, backgroundColor: colors.surface, borderColor: colors.brandPrimary,
    borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm,
    maxWidth: "92%",
  },
  proposalHeader: { flexDirection: "row", alignItems: "center", gap: 6 },
  proposalTitle: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.onSurface, fontWeight: "600", letterSpacing: 0.3 },
  proposalSummary: { fontSize: 13, color: colors.onSurfaceSecondary },
  proposalSection: { gap: 2, marginTop: 2 },
  proposalSectionLabel: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1, textTransform: "uppercase" },
  proposalItem: { fontSize: 13, color: colors.onSurface, lineHeight: 18 },
  proposalMore: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic" },
  feasibilityNote: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: colors.warning + "18", borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 6,
  },
  feasibilityText: { color: colors.warning, fontSize: 12, flex: 1, lineHeight: 17 },
  tradeoffRow: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: 2 },
  tradeoffBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, alignSelf: "flex-start" },
  tradeoffBadgeText: { fontSize: 9, fontWeight: "700", letterSpacing: 0.5 },
  applyBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingVertical: 10, borderRadius: radius.pill,
    marginTop: 4,
  },
  applyBtnText: { color: colors.onBrandPrimary, fontWeight: "600", fontSize: 13 },
  appliedRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  appliedText: { color: colors.success, fontSize: 13, fontWeight: "500" },
  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  errorText: { color: colors.error, fontSize: 13, flex: 1 },
  openersRow: {
    flexDirection: "row", flexWrap: "wrap", gap: spacing.xs,
    paddingHorizontal: spacing.lg, paddingBottom: spacing.sm,
  },
  opener: {
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.pill,
  },
  openerText: { fontSize: 12, color: colors.onSurface },
  inputRow: {
    flexDirection: "row", alignItems: "flex-end", gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  input: {
    flex: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10,
    fontSize: 15, color: colors.onSurface, maxHeight: 120,
  },
  sendBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
});
