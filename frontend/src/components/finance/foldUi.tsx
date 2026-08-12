/**
 * Fold-inspired reusable primitives for the Finance engine.
 *
 * These components ONLY change presentation. Any data, callbacks, testIDs and
 * IDs must be forwarded exactly as passed by the parent — the finance primitives
 * (position, commitments, forecast, events, scenarios) remain untouched.
 */

import React from "react";
import { Pressable, StyleSheet, Text, TextStyle, View, ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { financeColors, financeRadius, financeSpace, financeType } from "@/src/lib/finance/theme";

// ---------------------------------------------------------------------------
// Card — white surface floated on the greyed page. Rows inside share hairlines.
// ---------------------------------------------------------------------------
export function FoldCard({ children, style, testID }: { children: React.ReactNode; style?: ViewStyle; testID?: string }) {
  return <View style={[cardStyles.card, style]} testID={testID}>{children}</View>;
}

const cardStyles = StyleSheet.create({
  card: {
    backgroundColor: financeColors.card,
    borderRadius: financeRadius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: financeColors.cardBorder,
    overflow: "hidden",
  },
});

// ---------------------------------------------------------------------------
// SectionHeader — uppercase letter-spaced label with optional action link.
// ---------------------------------------------------------------------------
export function FoldSectionHeader({
  label,
  hint,
  action,
  testID,
}: {
  label: string;
  hint?: string;
  action?: { label: string; onPress: () => void; testID?: string };
  testID?: string;
}) {
  return (
    <View style={sectionStyles.wrap} testID={testID}>
      <View style={{ flex: 1 }}>
        <Text style={financeType.sectionLabel}>{label}</Text>
        {hint ? <Text style={sectionStyles.hint}>{hint}</Text> : null}
      </View>
      {action ? (
        <Pressable onPress={action.onPress} hitSlop={12} testID={action.testID}>
          <Text style={sectionStyles.action}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const sectionStyles = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "flex-end", gap: financeSpace.sm, marginBottom: financeSpace.sm, marginTop: financeSpace.xs, paddingHorizontal: 2 },
  hint: { fontSize: 11.5, color: financeColors.inkFaint, marginTop: 3 },
  action: { fontSize: 12.5, color: financeColors.accent, fontWeight: "600", letterSpacing: 0.2 },
});

// ---------------------------------------------------------------------------
// Row — a single line inside a card. Left label, right amount, optional chev.
// ---------------------------------------------------------------------------
export function FoldRow({
  label,
  meta,
  right,
  onPress,
  first,
  chevron,
  testID,
  strong,
  danger,
}: {
  label: string | React.ReactNode;
  meta?: string | React.ReactNode;
  right?: string | React.ReactNode;
  onPress?: () => void;
  first?: boolean;
  chevron?: boolean;
  testID?: string;
  strong?: boolean;
  danger?: boolean;
}) {
  const Wrap: any = onPress ? Pressable : View;
  return (
    <Wrap
      testID={testID}
      onPress={onPress}
      style={[rowStyles.row, !first && rowStyles.rowDivider]}
    >
      <View style={{ flex: 1 }}>
        {typeof label === "string" ? (
          <Text style={[financeType.rowLabel, strong && rowStyles.strongLabel]} numberOfLines={1}>{label}</Text>
        ) : (
          label
        )}
        {meta ? (
          typeof meta === "string" ? <Text style={financeType.rowMeta} numberOfLines={2}>{meta}</Text> : meta
        ) : null}
      </View>
      {right ? (
        typeof right === "string" ? (
          <Text style={[strong ? financeType.amountLg : financeType.amount, danger && { color: financeColors.danger }]}>
            {right}
          </Text>
        ) : (
          right
        )
      ) : null}
      {chevron && onPress ? (
        <Ionicons name="chevron-forward" size={14} color={financeColors.inkFaint} style={{ marginLeft: 6 }} />
      ) : null}
    </Wrap>
  );
}

const rowStyles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: financeSpace.lg,
    paddingVertical: 13,
    gap: financeSpace.md,
    backgroundColor: financeColors.card,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: financeColors.divider,
  },
  strongLabel: { fontWeight: "700" },
});

// ---------------------------------------------------------------------------
// Hero — very large display number for the top of a screen (e.g. Net Worth).
// ---------------------------------------------------------------------------
export function FoldHero({
  currency,
  amount,
  caption,
  size = "xl",
  testID,
}: {
  currency: string;
  amount: string;
  caption?: string;
  size?: "xl" | "l" | "m";
  testID?: string;
}) {
  const num = size === "xl" ? financeType.displayXL : size === "l" ? financeType.displayL : financeType.displayM;
  const curSize = size === "xl" ? 16 : size === "l" ? 14 : 12;
  return (
    <View style={heroStyles.wrap} testID={testID}>
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8 }}>
        <Text style={[heroStyles.currency, { fontSize: curSize }]}>{currency}</Text>
        <Text style={num as TextStyle}>{amount}</Text>
      </View>
      {caption ? <Text style={heroStyles.caption}>{caption}</Text> : null}
    </View>
  );
}

const heroStyles = StyleSheet.create({
  wrap: { paddingVertical: financeSpace.sm },
  currency: {
    fontFamily: "Georgia",
    color: financeColors.inkMuted,
    fontWeight: "600",
    letterSpacing: 0.5,
  },
  caption: {
    fontSize: 12,
    color: financeColors.inkMuted,
    marginTop: 6,
    letterSpacing: 0.3,
  },
});

// ---------------------------------------------------------------------------
// Pill — muted status pill (Fold doesn't use saturated chips).
// ---------------------------------------------------------------------------
export function FoldPill({
  label,
  tone = "neutral",
  size = "sm",
}: {
  label: string;
  tone?: "neutral" | "warn" | "err" | "ok" | "info";
  size?: "sm" | "xs";
}) {
  const palette = {
    neutral: { bg: financeColors.pillBg, fg: financeColors.pillInk },
    warn: { bg: financeColors.pillWarnBg, fg: financeColors.pillWarnInk },
    err: { bg: financeColors.pillErrBg, fg: financeColors.pillErrInk },
    ok: { bg: financeColors.pillOkBg, fg: financeColors.pillOkInk },
    info: { bg: financeColors.pillInfoBg, fg: financeColors.pillInfoInk },
  }[tone];
  return (
    <View
      style={{
        backgroundColor: palette.bg,
        paddingHorizontal: size === "xs" ? 6 : 8,
        paddingVertical: size === "xs" ? 2 : 3,
        borderRadius: financeRadius.pill,
        alignSelf: "flex-start",
      }}
    >
      <Text style={{ color: palette.fg, fontSize: size === "xs" ? 9.5 : 10.5, fontWeight: "700", letterSpacing: 0.8 }}>
        {label.toUpperCase()}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Amount — right-aligned tabular number (default helper for consistency).
// ---------------------------------------------------------------------------
export function FoldAmount({
  currency,
  value,
  size = "md",
  tone = "ink",
  sign,
}: {
  currency?: string;
  value: string;
  size?: "sm" | "md" | "lg" | "xl";
  tone?: "ink" | "positive" | "negative" | "muted";
  sign?: "+" | "-" | null;
}) {
  const face =
    size === "xl" ? financeType.displayL :
    size === "lg" ? financeType.displayM :
    size === "md" ? financeType.amountLg :
    financeType.amount;
  const color =
    tone === "positive" ? financeColors.positive :
    tone === "negative" ? financeColors.negative :
    tone === "muted" ? financeColors.inkMuted :
    financeColors.ink;
  return (
    <View style={{ flexDirection: "row", alignItems: "baseline", gap: 4, justifyContent: "flex-end" }}>
      {currency ? (
        <Text style={{ fontSize: (face as any).fontSize * 0.55, color: financeColors.inkMuted, fontWeight: "600", letterSpacing: 0.4 }}>
          {currency}
        </Text>
      ) : null}
      <Text style={[face as TextStyle, { color, textAlign: "right" }]}>
        {sign || ""}{value}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// FoldScreen — page background wrapper for consistent off-white surface.
// ---------------------------------------------------------------------------
export const foldPageStyle: ViewStyle = { flex: 1, backgroundColor: financeColors.page };

// ---------------------------------------------------------------------------
// SoftBanner — muted informational banner (replaces the loud brandTertiary).
// ---------------------------------------------------------------------------
export function FoldBanner({
  icon,
  text,
  action,
  tone = "neutral",
  testID,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  text: string;
  action?: { label: string; onPress: () => void; testID?: string };
  tone?: "neutral" | "warn" | "info";
  testID?: string;
}) {
  const bg =
    tone === "warn" ? financeColors.pillWarnBg :
    tone === "info" ? financeColors.pillInfoBg :
    "#F6F6F1";
  const ink =
    tone === "warn" ? financeColors.pillWarnInk :
    tone === "info" ? financeColors.pillInfoInk :
    financeColors.ink;
  return (
    <View
      testID={testID}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: financeSpace.md,
        paddingHorizontal: financeSpace.lg,
        paddingVertical: financeSpace.md,
        backgroundColor: bg,
        borderRadius: financeRadius.md,
        borderWidth: StyleSheet.hairlineWidth,
        borderColor: financeColors.cardBorder,
      }}
    >
      {icon ? <Ionicons name={icon} size={16} color={ink} /> : null}
      <Text style={{ flex: 1, fontSize: 13, color: ink, fontWeight: "500", lineHeight: 18 }}>{text}</Text>
      {action ? (
        <Pressable onPress={action.onPress} hitSlop={10} testID={action.testID}>
          <Text style={{ fontSize: 12.5, color: financeColors.accent, fontWeight: "700", letterSpacing: 0.3 }}>
            {action.label}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
