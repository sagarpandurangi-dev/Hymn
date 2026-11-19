import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { api, ApiError, InboxDecision, InboxItem } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";
import { formStyles as s } from "@/src/lib/formStyles";
import InboxItemRow from "@/src/components/InboxItemRow";

const CHOICES: { decision: InboxDecision; label: string }[] = [
  { decision: "done", label: "Done" },
  { decision: "discard", label: "Bin" },
  { decision: "nugget", label: "Gold" },
];

export default function DailyReviewScreen() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [items, setItems] = useState<InboxItem[]>([]);
  const [decisions, setDecisions] = useState<Record<string, InboxDecision>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api.getInboxReview();
      setPrompt(res.prompt || "");
      setItems(res.items || []);
      setDecisions({});
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

  const toggle = (id: string, d: InboxDecision) =>
    setDecisions((prev) => ({ ...prev, [id]: prev[id] === d ? "keep" : d }));

  const submit = async () => {
    if (submitting || items.length === 0) return;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const res = await api.submitInboxReview(
        items.map((it) => ({ item_id: it.id, decision: decisions[it.id] || "keep" })),
      );
      if ((res?.nuggets || []).length > 0) {
        router.push("/inbox/nuggets");
      } else {
        setNotice("Review saved.");
        await load();
      }
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="review-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Daily review</Text>
        <Pressable onPress={() => router.push("/inbox/nuggets")} hitSlop={12} testID="review-open-nuggets">
          <Text style={s.cancel}>Nuggets</Text>
        </Pressable>
      </View>
      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={[s.scroll, { gap: spacing.sm }]}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.brandPrimary} />}
        >
          {prompt ? <Text style={styles.prompt} testID="review-prompt">{prompt}</Text> : null}
          {notice ? <Text style={styles.notice} testID="review-notice">{notice}</Text> : null}
          {items.length === 0 && !error ? <Text style={styles.empty}>Nothing to review right now.</Text> : null}
          {items.map((it) => {
            const current = decisions[it.id] || "keep";
            return (
              <InboxItemRow key={it.id} text={it.text} category={it.category} testID={`review-item-${it.id}`}>
                <View style={styles.choiceRow}>
                  {CHOICES.map((c) => {
                    const sel = current === c.decision;
                    return (
                      <Pressable
                        key={c.decision}
                        onPress={() => toggle(it.id, c.decision)}
                        style={[s.chip, styles.choice, sel && s.chipSelected]}
                        testID={`review-${c.decision}-${it.id}`}
                      >
                        <Text style={[s.chipText, sel && s.chipTextSelected]}>{c.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </InboxItemRow>
            );
          })}
          {error ? <Text style={s.errorText} testID="review-error">{error}</Text> : null}
          {items.length > 0 ? (
            <Pressable
              style={[s.cta, { marginTop: spacing.lg }, submitting && s.ctaDisabled]}
              onPress={submit}
              disabled={submitting}
              testID="review-submit-button"
            >
              {submitting ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={s.ctaText}>Submit</Text>}
            </Pressable>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  prompt: { fontSize: 16, color: colors.onSurface, backgroundColor: colors.brandTertiary, padding: spacing.md, borderRadius: radius.sm, marginBottom: spacing.sm },
  notice: { fontSize: 13, color: colors.success },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary },
  choiceRow: { flexDirection: "row", gap: spacing.sm },
  choice: { flex: 1, minHeight: 44 },
});
