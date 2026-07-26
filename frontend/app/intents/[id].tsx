import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api, type ApiError } from "@/src/lib/api";
import {
  affordabilityLabel,
  affordabilityTone,
  intentFieldSourceLabel,
  missingDataLabel,
  type IntentFieldSource,
  type SavedIntent,
} from "@/src/lib/intents";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";


const errorMessage = (error: unknown): string =>
  (error as ApiError | undefined)?.message || "This intention could not be loaded.";

const evidenceSourceLabel = (
  source: string | undefined,
  kind: "known_fact" | "user_provided",
): string => {
  if (
    source
    && ["inferred_from_text", "user_edited", "known_profile", "marked_unknown", "missing"].includes(source)
  ) {
    return intentFieldSourceLabel(source as IntentFieldSource);
  }
  return kind === "known_fact" ? "Recorded in Hymn" : "Provided by you";
};

function ValueRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.valueRow}>
      <Text style={styles.valueLabel}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
  );
}

export default function IntentDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [intent, setIntent] = useState<SavedIntent | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setIntent(await api.getIntent(id));
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => {
    load();
  }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </SafeAreaView>
    );
  }

  if (!intent) {
    return (
      <SafeAreaView style={styles.center}>
        <Text style={styles.error}>{error || "Intention not found."}</Text>
        <Pressable style={styles.secondaryButton} onPress={() => router.replace("/intents")}>
          <Text style={styles.secondaryText}>Back to intentions</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  const analysis = intent.assessment;
  const snapshot = analysis.financial_snapshot;
  const tone = affordabilityTone(analysis.affordability_status);
  const selected = analysis.options.find((option) => option.id === intent.selected_option_id);

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.replace("/intents")} hitSlop={12} testID="intent-detail-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>Saved intention</Text>
          <Text style={styles.headerTitle} numberOfLines={1}>{intent.purchase.summary}</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.brandPrimary}
          />
        }
      >
        <View style={styles.hero}>
          <Text style={styles.heroTitle}>{intent.purchase.summary}</Text>
          <View style={[styles.badge, styles[`badge_${tone}`]]}>
            <Text style={[styles.badgeText, styles[`badgeText_${tone}`]]}>
              {affordabilityLabel(analysis.affordability_status)}
            </Text>
          </View>
          <Text style={styles.bodyText}>{analysis.recommended_next_action}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Purchase details</Text>
          <Text style={styles.originalSentence}>“{intent.original_text}”</Text>
          <ValueRow
            label="Expected price"
            value={
              intent.purchase.expected_price
                ? `${intent.purchase.currency || ""} ${intent.purchase.expected_price}`.trim()
                : "Not known yet"
            }
          />
          <ValueRow
            label="Desired timing"
            value={
              intent.purchase.desired_date
                ? intent.purchase.timing_text
                  ? `${intent.purchase.timing_text} → ${intent.purchase.desired_date}`
                  : intent.purchase.desired_date
                : "Not known yet"
            }
          />
          <ValueRow label="Plan status" value="Confirmed" />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Confirmed next step</Text>
          <Text style={styles.optionTitle}>{selected?.title || intent.selected_option_id}</Text>
          <Text style={styles.bodyText}>{selected?.description}</Text>
          {intent.downstream_records.map((row) => (
            <Pressable
              key={`${row.type}:${row.id}`}
              style={styles.linkRow}
              onPress={() => router.push(`/finance/commitments/${row.id}`)}
              testID={`intent-downstream-${row.id}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.optionTitle}>Draft money commitment</Text>
                <Text style={styles.bodyText}>Prepared in Finance; no money has been reserved.</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
            </Pressable>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Why Hymn reached this view</Text>
          {snapshot?.has_financial_data ? (
            <>
              <ValueRow
                label="Available before purchase"
                value={`${snapshot.currency || ""} ${snapshot.available_before_purchase || "—"}`.trim()}
              />
              <ValueRow
                label="Projected after purchase"
                value={`${snapshot.currency || ""} ${snapshot.projected_after_purchase || "—"}`.trim()}
              />
              <Text style={styles.note}>{snapshot.calculation}</Text>
            </>
          ) : (
            <Text style={styles.bodyText}>
              Hymn did not have enough relevant financial records to calculate affordability.
            </Text>
          )}
          {analysis.evidence.map((row) => (
            <View key={row.id} style={styles.evidenceRow}>
              <Ionicons
                name={row.kind === "known_fact" ? "checkmark-circle-outline" : "person-outline"}
                size={17}
                color={colors.brandPrimary}
              />
              <View style={{ flex: 1 }}>
                <Text style={styles.evidenceTitle}>{row.label}</Text>
                <Text style={styles.note}>
                  {evidenceSourceLabel(row.source, row.kind)} · {row.value}
                </Text>
              </View>
            </View>
          ))}
        </View>

        {analysis.missing_data.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Still missing</Text>
            {analysis.missing_data.map((field) => (
              <Text key={field} style={styles.bodyText}>• {missingDataLabel(field)}</Text>
            ))}
          </View>
        ) : null}

        {analysis.impacted_goals_or_commitments.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Plans that may be affected</Text>
            {analysis.impacted_goals_or_commitments.map((row) => (
              <View key={`${row.type}:${row.id}`} style={styles.impact}>
                <Text style={styles.optionTitle}>{row.title}</Text>
                <Text style={styles.bodyText}>{row.reason}</Text>
              </View>
            ))}
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Risks and trade-offs</Text>
          {analysis.risks_and_tradeoffs.map((risk) => (
            <Text key={risk} style={styles.bodyText}>• {risk}</Text>
          ))}
          <Text style={styles.disclaimer}>{analysis.disclaimer}</Text>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.lg,
    backgroundColor: colors.surface,
    padding: spacing.xl,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  eyebrow: { fontSize: 12, color: colors.onSurfaceSecondary },
  headerTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 20,
    fontWeight: "700",
    color: colors.onSurface,
  },
  scroll: { padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.lg },
  hero: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  heroTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 26,
    fontWeight: "700",
    color: colors.onBrandTertiary,
  },
  section: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  originalSentence: {
    fontSize: 14,
    lineHeight: 20,
    color: colors.onSurface,
    fontStyle: "italic",
  },
  bodyText: { fontSize: 13, lineHeight: 19, color: colors.onSurfaceSecondary },
  optionTitle: { fontSize: 14, fontWeight: "700", color: colors.onSurface },
  valueRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  valueLabel: { flex: 1, fontSize: 13, color: colors.onSurfaceSecondary },
  value: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  badge: {
    alignSelf: "flex-start",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  badge_success: { backgroundColor: "#E3EEE5" },
  badge_warning: { backgroundColor: "#F8EAD8" },
  badge_error: { backgroundColor: "#F5E3DF" },
  badge_neutral: { backgroundColor: colors.surfaceTertiary },
  badgeText: { fontSize: 12, fontWeight: "700" },
  badgeText_success: { color: colors.success },
  badgeText_warning: { color: "#8B5B20" },
  badgeText_error: { color: colors.error },
  badgeText_neutral: { color: colors.onSurfaceSecondary },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  evidenceRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  evidenceTitle: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  note: { fontSize: 12, lineHeight: 17, color: colors.onSurfaceTertiary },
  impact: { borderLeftWidth: 3, borderLeftColor: colors.brand, paddingLeft: spacing.md },
  disclaimer: { fontSize: 11, lineHeight: 16, color: colors.onSurfaceTertiary },
  error: {
    backgroundColor: "#F5E3DF",
    color: colors.error,
    borderRadius: radius.sm,
    padding: spacing.md,
  },
  secondaryButton: {
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  secondaryText: { color: colors.brandPrimary, fontWeight: "700" },
});
