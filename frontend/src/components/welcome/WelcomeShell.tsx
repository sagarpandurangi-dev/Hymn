import type { ReactNode } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export type StepNav = {
  index: number;
  total: number;
  back: () => void;
  skip: () => void;
  next: () => void;
};

type Props = {
  nav: StepNav;
  title: string;
  subtitle?: string;
  children?: ReactNode;
  primaryLabel: string;
  onPrimary: () => void;
  primaryDisabled?: boolean;
  busy?: boolean;
  error?: string | null;
  secondary?: { label: string; onPress: () => void; testID: string };
  hideSkip?: boolean;
};

/** One calm question per screen: progress line, Back, Skip (not on step 1), content, one main button. */
export default function WelcomeShell(p: Props) {
  const { nav } = p;
  const first = nav.index === 0;
  const pct = `${Math.round(((nav.index + 1) / nav.total) * 100)}%` as const;
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.progressTrack} testID="welcome-progress">
        <View style={[styles.progressFill, { width: pct }]} />
      </View>
      <View style={styles.topRow}>
        {first ? <View style={styles.topBtn} /> : (
          <Pressable onPress={nav.back} hitSlop={12} style={styles.topBtn} testID="welcome-back">
            <Text style={styles.topText}>Back</Text>
          </Pressable>
        )}
        <Text style={styles.stepCount}>{nav.index + 1} of {nav.total}</Text>
        {first || p.hideSkip ? <View style={styles.topBtn} /> : (
          <Pressable onPress={nav.skip} hitSlop={12} style={[styles.topBtn, { alignItems: "flex-end" }]} testID="welcome-skip">
            <Text style={styles.topText}>Skip</Text>
          </Pressable>
        )}
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.title} testID="welcome-title">{p.title}</Text>
          {p.subtitle ? <Text style={styles.subtitle}>{p.subtitle}</Text> : null}
          <View style={{ marginTop: spacing.xl }}>{p.children}</View>
        </ScrollView>
        <View style={styles.footer}>
          {p.error ? <Text style={styles.error} testID="welcome-error">{p.error}</Text> : null}
          <Pressable
            style={[styles.cta, (p.primaryDisabled || p.busy) && { opacity: 0.5 }]}
            onPress={p.onPrimary}
            disabled={p.primaryDisabled || p.busy}
            testID="welcome-primary"
          >
            {p.busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={styles.ctaText}>{p.primaryLabel}</Text>}
          </Pressable>
          {p.secondary ? (
            <Pressable onPress={p.secondary.onPress} style={styles.secondary} testID={p.secondary.testID} disabled={p.busy}>
              <Text style={styles.secondaryText}>{p.secondary.label}</Text>
            </Pressable>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  progressTrack: { height: 3, backgroundColor: colors.border, marginHorizontal: spacing.xl, marginTop: spacing.sm, borderRadius: 2 },
  progressFill: { height: 3, backgroundColor: colors.brandPrimary, borderRadius: 2 },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.sm },
  topBtn: { minWidth: 56, minHeight: 44, justifyContent: "center" },
  topText: { fontSize: 15, color: colors.onSurfaceSecondary },
  stepCount: { fontSize: 12, color: colors.onSurfaceTertiary, letterSpacing: 0.5 },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xxl },
  title: { fontFamily: fonts.displayBold, fontSize: 28, lineHeight: 36, fontWeight: "700", color: colors.onSurface },
  subtitle: { fontSize: 15, lineHeight: 22, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  footer: { paddingHorizontal: spacing.xl, paddingTop: spacing.sm, paddingBottom: spacing.md, gap: spacing.sm },
  error: { color: colors.error, fontSize: 13 },
  cta: { backgroundColor: colors.onSurface, minHeight: 52, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
  secondary: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  secondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "600" },
});
