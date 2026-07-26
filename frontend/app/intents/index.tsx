import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useColorScheme,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import DateTimeField from "@/src/components/DateTimeField";
import { api, type ApiError } from "@/src/lib/api";
import {
  affordabilityLabel,
  affordabilityTone,
  buildPurchaseUnderstanding,
  intentConfirmationKey,
  missingDataLabel,
  type IntentAnalysis,
  type SavedIntent,
} from "@/src/lib/intents";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";


const errorMessage = (error: unknown): string =>
  (error as ApiError | undefined)?.message || "Hymn could not complete that request.";

const pad = (value: number): string => value.toString().padStart(2, "0");

const localTodayISO = (): string => {
  const today = new Date();
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
};

function Header({ onBack }: { onBack: () => void }) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={12} testID="intent-back">
        <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
      </Pressable>
      <View style={{ flex: 1 }}>
        <Text style={styles.eyebrow}>A place to think before acting</Text>
        <Text style={styles.title}>I want to…</Text>
      </View>
    </View>
  );
}

function CheckRow({
  checked,
  label,
  onPress,
  testID,
}: {
  checked: boolean;
  label: string;
  onPress: () => void;
  testID: string;
}) {
  return (
    <Pressable style={styles.checkRow} onPress={onPress} testID={testID}>
      <Ionicons
        name={checked ? "checkbox" : "square-outline"}
        size={21}
        color={checked ? colors.brandPrimary : colors.onSurfaceTertiary}
      />
      <Text style={styles.checkText}>{label}</Text>
    </Pressable>
  );
}

function MoneyRow({
  label,
  value,
  currency,
}: {
  label: string;
  value: string | null;
  currency: string | null;
}) {
  return (
    <View style={styles.moneyRow}>
      <Text style={styles.moneyLabel}>{label}</Text>
      <Text style={styles.moneyValue}>
        {value === null ? "Not available" : `${currency || ""} ${value}`.trim()}
      </Text>
    </View>
  );
}

function UnderstandingCard({ analysis }: { analysis: IntentAnalysis }) {
  if (analysis.intent_type === "unsupported" || !analysis.purchase) {
    return (
      <View style={styles.understandingCard} testID="intent-understanding">
        <View style={styles.understandingHeader}>
          <Ionicons name="ear-outline" size={20} color={colors.brandPrimary} />
          <Text style={styles.understandingTitle}>Here’s what I heard</Text>
        </View>
        <Text style={styles.heardText}>“{analysis.original_text}”</Text>
        <View style={[styles.factChip, styles.factChipMissing]}>
          <Text style={styles.factChipLabel}>Intent</Text>
          <Text style={styles.factChipValue}>Not supported yet</Text>
        </View>
        <Text style={styles.bodyText}>{analysis.message}</Text>
      </View>
    );
  }

  const understanding = buildPurchaseUnderstanding(analysis);
  if (!understanding) return null;

  return (
    <View style={styles.understandingCard} testID="intent-understanding">
      <View style={styles.understandingHeader}>
        <Ionicons name="sparkles-outline" size={20} color={colors.brandPrimary} />
        <Text style={styles.understandingTitle}>Here’s what I understood</Text>
      </View>
      <Text style={styles.heardText}>“{analysis.original_text}”</Text>
      <View style={styles.factGrid}>
        {understanding.facts.map((fact) => (
          <View
            key={fact.key}
            style={[styles.factChip, fact.missing && styles.factChipMissing]}
            testID={`intent-understood-${fact.key}`}
          >
            <Text style={styles.factChipLabel}>{fact.label}</Text>
            <Text style={styles.factChipValue}>{fact.value}</Text>
            <Text style={styles.factChipSource}>{fact.source}</Text>
          </View>
        ))}
      </View>
      {understanding.timingResolution ? (
        <Text style={styles.inferenceNote}>{understanding.timingResolution}</Text>
      ) : null}
      {understanding.missingEssentials.length > 0 ? (
        <View style={styles.stillNeed}>
          <Text style={styles.stillNeedTitle}>I still need…</Text>
          <Text style={styles.bodyText} testID="intent-still-needs">
            {understanding.missingEssentials.map(missingDataLabel).join(" · ")}
          </Text>
          {analysis.clarification_questions
            .filter((question) =>
              understanding.missingEssentials.includes(question.field),
            )
            .map((question) => (
              <Text key={question.field} style={styles.clarificationText}>
                {question.question}
              </Text>
            ))}
        </View>
      ) : (
        <Text style={styles.readyLine}>You can correct these details before confirming.</Text>
      )}
    </View>
  );
}

export default function IntentHomeScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const [text, setText] = useState("");
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState("");
  const [desiredDate, setDesiredDate] = useState("");
  const [priceUnknown, setPriceUnknown] = useState(false);
  const [timingUnknown, setTimingUnknown] = useState(false);
  const [analysis, setAnalysis] = useState<IntentAnalysis | null>(null);
  const [selectedOption, setSelectedOption] = useState("");
  const [confirmationKey, setConfirmationKey] = useState(intentConfirmationKey);
  const [saved, setSaved] = useState<SavedIntent[]>([]);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerFocused, setComposerFocused] = useState(false);
  const [composerHeight, setComposerHeight] = useState(112);
  const [assessmentDirty, setAssessmentDirty] = useState(false);

  const composerPalette = colorScheme === "dark"
    ? {
      surface: "#171A16",
      text: "#F7F8F4",
      placeholder: "#B9C0B3",
      border: "#697361",
      cursor: "#DDE8D6",
    }
    : {
      surface: "#FFFFFF",
      text: "#1E1E1C",
      placeholder: "#6F716A",
      border: colors.borderStrong,
      cursor: colors.brandPrimary,
    };

  const loadSaved = useCallback(async () => {
    try {
      setSaved(await api.listIntents());
    } catch {
      // The entry journey remains useful if history cannot be loaded.
    }
  }, []);

  useFocusEffect(useCallback(() => {
    loadSaved();
  }, [loadSaved]));

  const purchasePayload = () => {
    const sources = analysis?.purchase?.field_sources;
    const inferredPurchase = analysis?.purchase;
    const priceValue = price.trim();
    const currencyValue = currency.trim().toUpperCase();
    const priceIsUnchangedInference = (
      sources?.expected_price === "inferred_from_text"
      && priceValue === inferredPurchase?.expected_price
    );
    const currencyIsUnchangedKnownValue = (
      ["inferred_from_text", "known_profile"].includes(sources?.currency || "")
      && currencyValue === inferredPurchase?.currency
    );
    const dateIsUnchangedInference = (
      sources?.desired_date === "inferred_from_text"
      && desiredDate === inferredPurchase?.desired_date
    );
    return {
      expected_price: (
        priceUnknown || !priceValue || priceIsUnchangedInference
          ? undefined
          : priceValue
      ),
      currency: (
        !currencyValue || currencyIsUnchangedKnownValue
          ? undefined
          : currencyValue
      ),
      desired_date: (
        timingUnknown || !desiredDate || dateIsUnchangedInference
          ? undefined
          : desiredDate
      ),
      price_unknown: priceUnknown,
      timing_unknown: timingUnknown,
    };
  };

  const handleTextChange = (value: string) => {
    setText(value);
    if (!analysis) return;
    setAnalysis(null);
    setAssessmentDirty(false);
    setSelectedOption("");
    setPrice("");
    setCurrency("");
    setDesiredDate("");
    setPriceUnknown(false);
    setTimingUnknown(false);
    setError(null);
    setConfirmationKey(intentConfirmationKey());
  };

  const assess = async () => {
    setError(null);
    if (!text.trim()) {
      setError("Tell Hymn what you want to do.");
      return;
    }
    setBusy(true);
    try {
      const result = await api.analyzeIntent({
        text: text.trim(),
        purchase: purchasePayload(),
        reference_date: localTodayISO(),
      });
      setAnalysis(result);
      setAssessmentDirty(false);
      setSelectedOption(result.recommended_option_id || result.options[0]?.id || "");
      setConfirmationKey(intentConfirmationKey());
      if (result.purchase) {
        setPrice(result.purchase.expected_price || "");
        setCurrency(result.purchase.currency || "");
        setDesiredDate(result.purchase.desired_date || "");
        setPriceUnknown(result.purchase.price_unknown);
        setTimingUnknown(result.purchase.timing_unknown);
      }
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!analysis?.can_confirm || !selectedOption || assessmentDirty) return;
    setError(null);
    setBusy(true);
    try {
      const savedIntent = await api.confirmIntent({
        text: text.trim(),
        purchase: purchasePayload(),
        reference_date: localTodayISO(),
        selected_option_id: selectedOption,
        idempotency_key: confirmationKey,
      });
      router.replace(`/intents/${savedIntent.id}`);
    } catch (requestError: unknown) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadSaved();
    setRefreshing(false);
  };

  const tone = analysis ? affordabilityTone(analysis.affordability_status) : "neutral";
  const snapshot = analysis?.financial_snapshot;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <Header onBack={() => router.back()} />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <View style={styles.introCard}>
            <Text style={styles.introTitle}>What is on your mind?</Text>
            <Text style={styles.bodyText}>
              Hymn will separate what it knows, what you are assuming, and what still needs attention.
            </Text>
            <TextInput
              value={text}
              onChangeText={handleTextChange}
              editable={!busy}
              multiline
              spellCheck
              accessibilityLabel="Describe what you want to do"
              placeholder="Try: Buy an iPad for ₹80,000 by December 15"
              placeholderTextColor={composerPalette.placeholder}
              selectionColor={composerPalette.cursor}
              cursorColor={composerPalette.cursor}
              keyboardAppearance={colorScheme === "dark" ? "dark" : "light"}
              onFocus={() => setComposerFocused(true)}
              onBlur={() => setComposerFocused(false)}
              onContentSizeChange={(event) => {
                const nextHeight = Math.max(
                  112,
                  Math.min(196, event.nativeEvent.contentSize.height + spacing.xl),
                );
                setComposerHeight(nextHeight);
              }}
              style={[
                styles.intentInput,
                {
                  height: composerHeight,
                  backgroundColor: composerPalette.surface,
                  borderColor: composerFocused ? composerPalette.cursor : composerPalette.border,
                  color: composerPalette.text,
                },
                composerFocused && styles.intentInputFocused,
              ]}
              testID="intent-natural-language-input"
            />
            <View style={styles.composerFooter}>
              <Text style={styles.composerHint}>
                Hymn reads only what you wrote. It does not look up products or prices.
              </Text>
              <Pressable
                onPress={assess}
                disabled={busy || !text.trim()}
                accessibilityState={{ disabled: busy || !text.trim() }}
                style={[
                  styles.primaryButton,
                  styles.composerSubmit,
                  (busy || !text.trim()) && styles.disabled,
                ]}
                testID="intent-assess"
              >
                {busy ? (
                  <ActivityIndicator color={colors.onBrandPrimary} />
                ) : (
                  <Text style={styles.primaryText}>
                    {analysis ? "Read it again" : "Understand this"}
                  </Text>
                )}
              </Pressable>
            </View>
          </View>

          {error ? <Text style={styles.error}>{error}</Text> : null}

          {analysis ? <UnderstandingCard analysis={analysis} /> : null}

          {analysis?.intent_type === "purchase" ? (
            <>
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Essential details</Text>
                <Text style={styles.bodyText}>
                  Only add what you know. Unknown values remain visible in the plan.
                </Text>
                <Text style={styles.label}>Expected price</Text>
                <View style={styles.splitRow}>
                  <TextInput
                    value={price}
                    onChangeText={(value) => {
                      setPrice(value);
                      setAssessmentDirty(true);
                    }}
                    editable={!priceUnknown && !busy}
                    keyboardType="decimal-pad"
                    placeholder="0.00"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={[styles.input, { flex: 2 }, priceUnknown && styles.disabledInput]}
                    testID="intent-price"
                  />
                  <TextInput
                    value={currency}
                    onChangeText={(value) => {
                      setCurrency(value.toUpperCase().slice(0, 3));
                      setAssessmentDirty(true);
                    }}
                    editable={!priceUnknown && !busy}
                    autoCapitalize="characters"
                    placeholder="USD"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={[styles.input, { flex: 1 }, priceUnknown && styles.disabledInput]}
                    testID="intent-currency"
                  />
                </View>
                <CheckRow
                  checked={priceUnknown}
                  label="I don’t know the price yet"
                  onPress={() => {
                    setPriceUnknown((value) => !value);
                    setPrice("");
                    setAssessmentDirty(true);
                  }}
                  testID="intent-price-unknown"
                />

                <Text style={styles.label}>When would you like to buy it?</Text>
                <DateTimeField
                  mode="date"
                  value={desiredDate}
                  onChange={(value) => {
                    setDesiredDate(value);
                    setAssessmentDirty(true);
                  }}
                  clearable
                  testID="intent-desired-date"
                />
                <CheckRow
                  checked={timingUnknown}
                  label="I don’t know the timing yet"
                  onPress={() => {
                    setTimingUnknown((value) => !value);
                    setDesiredDate("");
                    setAssessmentDirty(true);
                  }}
                  testID="intent-timing-unknown"
                />

                <Pressable
                  onPress={assess}
                  disabled={busy}
                  style={[styles.secondaryButton, busy && styles.disabled]}
                  testID="intent-update-assessment"
                >
                  <Text style={styles.secondaryText}>
                    {busy ? "Updating…" : "Update assessment"}
                  </Text>
                </Pressable>
              </View>

              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Purchase summary</Text>
                <Text style={styles.summary}>{analysis.purchase?.summary}</Text>
                <View style={[styles.badge, styles[`badge_${tone}`]]}>
                  <Text style={[styles.badgeText, styles[`badgeText_${tone}`]]}>
                    {affordabilityLabel(analysis.affordability_status)}
                  </Text>
                </View>
                <Text style={styles.bodyText}>{analysis.recommended_next_action}</Text>
              </View>

              <View style={styles.section}>
                <Text style={styles.sectionTitle}>What Hymn used</Text>
                {snapshot?.has_financial_data ? (
                  <>
                    <MoneyRow label="Recorded liquid assets" value={snapshot.liquid_assets} currency={snapshot.currency} />
                    <MoneyRow label="Planned income" value={snapshot.planned_income} currency={snapshot.currency} />
                    <MoneyRow label="Planned outflows" value={snapshot.planned_outflows} currency={snapshot.currency} />
                    <MoneyRow label="Savings and investments" value={snapshot.planned_savings_and_investments} currency={snapshot.currency} />
                    <MoneyRow label="Reserved commitments due" value={snapshot.reserved_commitments_due} currency={snapshot.currency} />
                    <MoneyRow label="Available before purchase" value={snapshot.available_before_purchase} currency={snapshot.currency} />
                    <MoneyRow label="Projected after purchase" value={snapshot.projected_after_purchase} currency={snapshot.currency} />
                    <Text style={styles.note}>Calculation: {snapshot.calculation}</Text>
                  </>
                ) : (
                  <Text style={styles.bodyText}>
                    No relevant financial records were available for this currency and timing.
                  </Text>
                )}
                <Text style={styles.note}>
                  Queried: {analysis.contexts_queried.length > 0
                    ? analysis.contexts_queried.join(", ").replaceAll("_", " ")
                    : "no portfolio context"}
                </Text>
              </View>

              {analysis.missing_data.length > 0 ? (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Still missing</Text>
                  {analysis.missing_data.map((field) => (
                    <View key={field} style={styles.bulletRow}>
                      <Ionicons name="ellipse" size={7} color={colors.warning} />
                      <Text style={styles.bodyText}>{missingDataLabel(field)}</Text>
                    </View>
                  ))}
                </View>
              ) : null}

              {analysis.impacted_goals_or_commitments.length > 0 ? (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Plans that may be affected</Text>
                  {analysis.impacted_goals_or_commitments.map((row) => (
                    <View key={`${row.type}:${row.id}`} style={styles.impactCard}>
                      <Text style={styles.impactTitle}>{row.title}</Text>
                      <Text style={styles.bodyText}>{row.reason}</Text>
                    </View>
                  ))}
                </View>
              ) : null}

              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Risks and trade-offs</Text>
                {analysis.risks_and_tradeoffs.map((risk) => (
                  <View key={risk} style={styles.bulletRow}>
                    <Ionicons name="ellipse" size={7} color={colors.onSurfaceTertiary} />
                    <Text style={styles.bodyText}>{risk}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Choose what happens next</Text>
                <Text style={styles.bodyText}>
                  Review first. Hymn will perform only the option you confirm.
                </Text>
                {analysis.options.map((option) => {
                  const selected = selectedOption === option.id;
                  return (
                    <Pressable
                      key={option.id}
                      onPress={() => setSelectedOption(option.id)}
                      style={[styles.option, selected && styles.optionSelected]}
                      testID={`intent-option-${option.id}`}
                    >
                      <Ionicons
                        name={selected ? "radio-button-on" : "radio-button-off"}
                        size={21}
                        color={selected ? colors.brandPrimary : colors.onSurfaceTertiary}
                      />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.optionTitle}>{option.title}</Text>
                        <Text style={styles.bodyText}>{option.description}</Text>
                      </View>
                    </Pressable>
                  );
                })}
                <Pressable
                  onPress={confirm}
                  disabled={!analysis.can_confirm || !selectedOption || busy || assessmentDirty}
                  style={[
                    styles.primaryButton,
                    (!analysis.can_confirm || !selectedOption || busy || assessmentDirty)
                      && styles.disabled,
                  ]}
                  testID="intent-confirm"
                >
                  {busy ? (
                    <ActivityIndicator color={colors.onBrandPrimary} />
                  ) : (
                    <Text style={styles.primaryText}>Confirm this plan</Text>
                  )}
                </Pressable>
                {!analysis.can_confirm ? (
                  <Text style={styles.note}>
                    Answer the essential questions above, or mark them as unknown, before confirming.
                  </Text>
                ) : assessmentDirty ? (
                  <Text style={styles.note}>
                    Update the assessment so Hymn uses your corrected details before confirming.
                  </Text>
                ) : null}
                <Text style={styles.disclaimer}>{analysis.disclaimer}</Text>
              </View>
            </>
          ) : null}

          {saved.length > 0 ? (
            <View style={styles.history}>
              <Text style={styles.sectionTitle}>Saved intentions</Text>
              {saved.map((row) => (
                <Pressable
                  key={row.id}
                  style={styles.savedRow}
                  onPress={() => router.push(`/intents/${row.id}`)}
                  testID={`intent-saved-${row.id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.savedTitle}>{row.purchase.summary}</Text>
                    <Text style={styles.note}>
                      {affordabilityLabel(row.assessment.affordability_status)}
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
                </Pressable>
              ))}
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  eyebrow: { fontSize: 12, color: colors.onSurfaceSecondary },
  title: {
    fontFamily: fonts.displayBold,
    fontSize: 27,
    fontWeight: "700",
    color: colors.onSurface,
  },
  scroll: { padding: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.lg },
  introCard: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  introTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 22,
    fontWeight: "700",
    color: colors.onBrandTertiary,
  },
  intentInput: {
    minHeight: 112,
    maxHeight: 196,
    borderRadius: radius.md,
    borderWidth: 2,
    padding: spacing.lg,
    fontSize: 16,
    lineHeight: 23,
    textAlignVertical: "top",
  },
  intentInputFocused: {
    shadowColor: colors.brandPrimary,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 7,
    elevation: 2,
  },
  composerFooter: { gap: spacing.md },
  composerHint: { fontSize: 12, lineHeight: 17, color: colors.onBrandTertiary },
  composerSubmit: { alignSelf: "flex-end", minWidth: 154, paddingHorizontal: spacing.xl },
  understandingCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    padding: spacing.xl,
    gap: spacing.md,
  },
  understandingHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  understandingTitle: {
    flex: 1,
    fontFamily: fonts.displayBold,
    fontSize: 19,
    fontWeight: "700",
    color: colors.onSurface,
  },
  heardText: {
    fontSize: 14,
    lineHeight: 21,
    color: colors.onSurface,
    fontStyle: "italic",
  },
  factGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  factChip: {
    minWidth: 132,
    flexGrow: 1,
    flexBasis: "45%",
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: 2,
  },
  factChipMissing: {
    backgroundColor: "#F8EAD8",
    borderWidth: 1,
    borderColor: "#E5C69F",
  },
  factChipLabel: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    letterSpacing: 0.7,
    textTransform: "uppercase",
  },
  factChipValue: { fontSize: 14, color: colors.onSurface, fontWeight: "700" },
  factChipSource: { fontSize: 10, lineHeight: 14, color: colors.onSurfaceSecondary },
  inferenceNote: {
    fontSize: 11,
    lineHeight: 16,
    color: colors.onSurfaceTertiary,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.sm,
  },
  stillNeed: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
    gap: spacing.xs,
  },
  stillNeedTitle: { fontSize: 13, fontWeight: "700", color: colors.warning },
  clarificationText: {
    fontSize: 12,
    lineHeight: 18,
    color: colors.onSurface,
    fontWeight: "600",
  },
  readyLine: { fontSize: 12, lineHeight: 17, color: colors.success, fontWeight: "600" },
  section: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  bodyText: { fontSize: 13, lineHeight: 19, color: colors.onSurfaceSecondary },
  summary: {
    fontFamily: fonts.displayBold,
    fontSize: 21,
    fontWeight: "700",
    color: colors.onSurface,
  },
  label: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  splitRow: { flexDirection: "row", gap: spacing.sm },
  input: {
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.onSurface,
    fontSize: 15,
  },
  disabledInput: { opacity: 0.45 },
  checkRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  checkText: { fontSize: 13, color: colors.onSurfaceSecondary },
  primaryButton: {
    minHeight: 48,
    borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  primaryText: { color: colors.onBrandPrimary, fontSize: 15, fontWeight: "700" },
  secondaryButton: {
    minHeight: 44,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: { color: colors.brandPrimary, fontSize: 14, fontWeight: "700" },
  textButton: { paddingVertical: spacing.xs, alignItems: "center" },
  textButtonLabel: { color: colors.onBrandTertiary, fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.45 },
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
  moneyRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    paddingBottom: spacing.sm,
  },
  moneyLabel: { flex: 1, fontSize: 13, color: colors.onSurfaceSecondary },
  moneyValue: { fontSize: 13, fontWeight: "600", color: colors.onSurface },
  note: { fontSize: 12, lineHeight: 17, color: colors.onSurfaceTertiary },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  impactCard: { borderLeftWidth: 3, borderLeftColor: colors.brand, paddingLeft: spacing.md },
  impactTitle: { fontSize: 14, fontWeight: "700", color: colors.onSurface },
  option: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  optionSelected: { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary },
  optionTitle: { fontSize: 14, fontWeight: "700", color: colors.onSurface, marginBottom: 2 },
  disclaimer: { fontSize: 11, lineHeight: 16, color: colors.onSurfaceTertiary },
  error: {
    backgroundColor: "#F5E3DF",
    color: colors.error,
    borderRadius: radius.sm,
    padding: spacing.md,
    fontSize: 13,
  },
  history: { gap: spacing.sm, marginTop: spacing.md },
  savedRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  savedTitle: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
});
