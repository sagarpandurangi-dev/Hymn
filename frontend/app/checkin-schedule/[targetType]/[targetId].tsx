import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type TargetType = "goal" | "project";
type Cadence = "" | "daily" | "weekly" | "monthly" | "manual";

type ScheduleTarget = {
  id: string;
  title: string;
  checkin_cadence: string;
};

const OPTIONS: { value: Cadence; label: string; detail: string }[] = [
  {
    value: "daily",
    label: "Daily",
    detail: "Plan to review progress once a day.",
  },
  {
    value: "weekly",
    label: "Weekly",
    detail: "Review progress once in each calendar week.",
  },
  {
    value: "monthly",
    label: "Monthly",
    detail: "Review progress once in each calendar month.",
  },
  {
    value: "manual",
    label: "Only when I choose",
    detail: "Keep progress logging available without a recurring reminder.",
  },
  {
    value: "",
    label: "No schedule",
    detail: "Remove the recurring check-in schedule. Existing progress logs stay unchanged.",
  },
];

function isTargetType(value: string | undefined): value is TargetType {
  return value === "goal" || value === "project";
}

function isCadence(value: string | undefined): value is Cadence {
  return OPTIONS.some((option) => option.value === (value || ""));
}

export default function CheckinScheduleScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ targetType?: string; targetId?: string }>();
  const targetType = typeof params.targetType === "string" ? params.targetType : undefined;
  const targetId = typeof params.targetId === "string" ? params.targetId : undefined;

  const [target, setTarget] = useState<ScheduleTarget | null>(null);
  const [cadence, setCadence] = useState<Cadence>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      if (!isTargetType(targetType) || !targetId) {
        setError("This check-in schedule link is not valid.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const result =
          targetType === "goal"
            ? await api.getGoal(targetId)
            : await api.getProject(targetId);
        if (!active) return;
        const scheduleTarget: ScheduleTarget = {
          id: result.id,
          title: result.title,
          checkin_cadence: result.checkin_cadence || "",
        };
        setTarget(scheduleTarget);
        setCadence(isCadence(scheduleTarget.checkin_cadence) ? scheduleTarget.checkin_cadence : "");
      } catch (caught) {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Could not load this schedule.");
      } finally {
        if (active) setLoading(false);
      }
    };

    load();
    return () => {
      active = false;
    };
  }, [targetId, targetType]);

  const save = async () => {
    if (!target || !isTargetType(targetType)) return;
    setSaving(true);
    setError(null);
    try {
      if (targetType === "goal") {
        await api.updateGoal(target.id, { checkin_cadence: cadence });
      } else {
        await api.updateProject(target.id, { checkin_cadence: cadence });
      }
      router.back();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save this schedule.");
    } finally {
      setSaving(false);
    }
  };

  const targetLabel = targetType === "project" ? "project" : "goal";

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          hitSlop={12}
          testID="checkin-schedule-cancel"
        >
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Set check-in schedule</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : !target ? (
        <View style={styles.center}>
          <Text style={styles.error} testID="checkin-schedule-load-error">
            {error || "This goal or project could not be found."}
          </Text>
          <Pressable onPress={() => router.back()} style={styles.backButton}>
            <Text style={styles.backButtonText}>Go back</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <ScrollView contentContainerStyle={styles.scroll}>
            <Text style={styles.eyebrow}>{targetLabel.toUpperCase()}</Text>
            <Text style={styles.title}>{target.title}</Text>
            <Text style={styles.intro}>
              Choose how often you intend to review progress. Hymn stores this
              preference separately; saving it does not create a progress log.
            </Text>

            <View style={styles.options}>
              {OPTIONS.map((option) => {
                const selected = cadence === option.value;
                return (
                  <Pressable
                    key={option.value || "none"}
                    onPress={() => setCadence(option.value)}
                    style={[styles.option, selected && styles.optionSelected]}
                    testID={`checkin-schedule-option-${option.value || "none"}`}
                  >
                    <View style={styles.optionCopy}>
                      <Text style={styles.optionTitle}>{option.label}</Text>
                      <Text style={styles.optionDetail}>{option.detail}</Text>
                    </View>
                    <Ionicons
                      name={selected ? "radio-button-on" : "radio-button-off"}
                      size={22}
                      color={selected ? colors.brandPrimary : colors.onSurfaceTertiary}
                    />
                  </Pressable>
                );
              })}
            </View>

            {error ? (
              <Text style={styles.error} testID="checkin-schedule-save-error">
                {error}
              </Text>
            ) : null}
          </ScrollView>

          <View style={styles.footer}>
            <Pressable
              onPress={save}
              disabled={saving}
              style={[styles.saveButton, saving && styles.disabled]}
              testID="checkin-schedule-save"
            >
              {saving ? (
                <ActivityIndicator color={colors.onBrandPrimary} />
              ) : (
                <Text style={styles.saveButtonText}>Save schedule</Text>
              )}
            </Pressable>
          </View>
        </>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
  },
  headerTitle: {
    color: colors.onSurface,
    fontFamily: fonts.displayBold,
    fontSize: 17,
    fontWeight: "700",
  },
  headerSpacer: { width: 22 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.lg,
    paddingHorizontal: spacing.xl,
  },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  eyebrow: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    letterSpacing: 1.5,
    marginTop: spacing.md,
  },
  title: {
    color: colors.onSurface,
    fontFamily: fonts.displayBold,
    fontSize: 26,
    fontWeight: "700",
    lineHeight: 34,
    marginTop: spacing.xs,
  },
  intro: {
    color: colors.onSurfaceSecondary,
    fontSize: 15,
    lineHeight: 23,
    marginTop: spacing.md,
  },
  options: { gap: spacing.sm, marginTop: spacing.xl },
  option: {
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    borderWidth: 1,
    flexDirection: "row",
    gap: spacing.md,
    padding: spacing.lg,
  },
  optionSelected: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  optionCopy: { flex: 1 },
  optionTitle: { color: colors.onSurface, fontSize: 15, fontWeight: "600" },
  optionDetail: {
    color: colors.onSurfaceSecondary,
    fontSize: 13,
    lineHeight: 19,
    marginTop: spacing.xs,
  },
  error: { color: colors.error, fontSize: 13, lineHeight: 19, marginTop: spacing.md },
  backButton: {
    borderColor: colors.brandPrimary,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
  },
  backButtonText: { color: colors.brandPrimary, fontSize: 14, fontWeight: "600" },
  footer: {
    borderTopColor: colors.surfaceTertiary,
    borderTopWidth: 1,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.lg,
  },
  saveButton: {
    alignItems: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    justifyContent: "center",
    minHeight: 48,
  },
  saveButtonText: {
    color: colors.onBrandPrimary,
    fontFamily: fonts.displayBold,
    fontSize: 15,
    fontWeight: "700",
  },
  disabled: { opacity: 0.55 },
});
