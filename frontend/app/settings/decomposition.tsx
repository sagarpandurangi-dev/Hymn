import React, { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import { useAuth } from "@/src/lib/AuthContext";
import type { PostCreationDecompositionPreference } from "@/src/lib/AuthContext";

const OPTIONS: { value: PostCreationDecompositionPreference; label: string; description: string }[] = [
  {
    value: "always_ask",
    label: "Always ask",
    description: "Show a choice each time after creation.",
  },
  {
    value: "always_decompose",
    label: "Always decompose",
    description: "Go straight to Plan with Hymn after creation.",
  },
  {
    value: "always_skip",
    label: "Always skip",
    description: "Go straight to the detail page after creation.",
  },
];

export default function DecompositionSettingsScreen() {
  const router = useRouter();
  const { user, setPostCreationDecompositionPreference } = useAuth();
  const current = (user?.post_creation_decomposition_preference as PostCreationDecompositionPreference) || "always_ask";
  const [busy, setBusy] = useState<PostCreationDecompositionPreference | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pick = async (value: PostCreationDecompositionPreference) => {
    if (busy || value === current) return;
    setBusy(value);
    setError(null);
    try {
      await setPostCreationDecompositionPreference(value);
    } catch {
      setError("Could not save your preference. Please try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="decomposition-back">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Planning after creation</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Planning after creation</Text>
        <Text style={styles.description}>
          After creating a goal, project or learning journey:
        </Text>

        {OPTIONS.map((opt) => {
          const selected = current === opt.value;
          const loading = busy === opt.value;
          return (
            <Pressable
              key={opt.value}
              onPress={() => pick(opt.value)}
              disabled={!!busy}
              style={[styles.optionRow, selected && styles.optionRowSelected]}
              testID={`decomposition-option-${opt.value}`}
            >
              <Ionicons
                name={selected ? "radio-button-on" : "radio-button-off"}
                size={22}
                color={selected ? colors.brandPrimary : colors.onSurfaceSecondary}
              />
              <View style={styles.optionText}>
                <Text style={styles.optionLabel}>{opt.label}</Text>
                <Text style={styles.optionDescription}>{opt.description}</Text>
              </View>
              {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
            </Pressable>
          );
        })}

        {error ? <Text style={styles.errorText} testID="decomposition-error">{error}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: colors.onSurface },
  scroll: { padding: spacing.lg, gap: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface },
  description: {
    fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary,
    marginBottom: spacing.sm,
  },
  optionRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.md,
    borderRadius: radius.md, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
  },
  optionRowSelected: { borderColor: colors.brandPrimary },
  optionText: { flex: 1 },
  optionLabel: { fontFamily: fonts.displayBold, fontSize: 15, color: colors.onSurface },
  optionDescription: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  errorText: {
    fontFamily: fonts.body, fontSize: 13, color: colors.error,
    marginTop: spacing.md,
  },
});
