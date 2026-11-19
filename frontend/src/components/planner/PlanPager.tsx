/**
 * Swipe between the plans a conversation produced; "Go with this" accepts one.
 */
import { useState } from "react";
import { ActivityIndicator, NativeScrollEvent, NativeSyntheticEvent, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, ApiError } from "@/src/lib/api";
import PlanCard from "@/src/components/planner/PlanCard";
import { colors, radius, spacing } from "@/src/lib/theme";

export default function PlanPager({ plans, width, onChanged }: { plans: any[]; width: number; onChanged: (p: any) => void }) {
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const many = plans.length > 1;

  const accept = async (id: string) => {
    setBusy(id);
    setError("");
    try {
      await api.acceptLifePlan(id);
      onChanged(await api.getLifePlan(id));
    } catch (e) {
      setError((e as ApiError).message || "Couldn't pick this plan. Try again.");
    } finally {
      setBusy("");
    }
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const i = Math.round(e.nativeEvent.contentOffset.x / width);
    if (i !== index) setIndex(i);
  };

  const footer = (p: any) =>
    p.status === "draft" || !p.status ? (
      <Pressable style={styles.go} disabled={!!busy} onPress={() => accept(p.id)} testID={`plan-accept-${p.id}`}>
        {busy === p.id ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.goText}>Go with this</Text>}
      </Pressable>
    ) : (
      <Text style={styles.chosen} testID={`plan-chosen-${p.id}`}>You&apos;re going with this plan.</Text>
    );

  return (
    <View testID="plan-pager">
      {many ? <Text style={styles.count}>Plan {index + 1} of {plans.length} · swipe to compare</Text> : null}
      <ScrollView horizontal pagingEnabled={many} scrollEnabled={many} showsHorizontalScrollIndicator={false} onMomentumScrollEnd={onScroll} onScroll={onScroll} scrollEventThrottle={64}>
        {plans.map((p) => (
          <View key={p.id} style={{ width }}>
            <PlanCard plan={p} onChanged={onChanged} footer={footer(p)} />
          </View>
        ))}
      </ScrollView>
      {many ? (
        <View style={styles.dots}>
          {plans.map((p, i) => <View key={p.id} style={[styles.dot, i === index && styles.dotOn]} />)}
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  count: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  dots: { flexDirection: "row", justifyContent: "center", gap: 6, marginTop: spacing.sm },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.borderStrong },
  dotOn: { backgroundColor: colors.onSurface, width: 16 },
  go: { marginTop: spacing.md, minHeight: 48, borderRadius: radius.pill, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  goText: { color: colors.onBrandPrimary, fontSize: 15, fontWeight: "700" },
  chosen: { marginTop: spacing.md, fontSize: 14, fontWeight: "600", color: colors.success, textAlign: "center" },
  error: { marginTop: spacing.sm, fontSize: 13, color: colors.error },
});
