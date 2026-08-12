/**
 * Fold-inspired finance visual language.
 *
 * Design intent (per user brief):
 *   • Big heavy display type for numbers (tabular, right-aligned)
 *   • Calm off-white page surface, white cards floated on grey
 *   • Hairline dividers between rows (no per-row cards)
 *   • Letter-spaced uppercase section labels
 *   • Restrained accent — Hymn's sage brand tint used sparingly for links
 *   • Muted status pills instead of saturated chips
 *
 * These tokens are strictly presentational — no math, no primitives touched.
 */

import { Platform } from "react-native";
import { colors } from "@/src/lib/theme";

export const financeColors = {
  // Surfaces
  page: "#F1F1EC",           // calm off-white page background (greyer than app surface)
  card: "#FFFFFF",           // white cards floated on grey
  cardBorder: "#E7E7E1",     // hairline border for cards
  divider: "#ECECE6",        // in-card row dividers

  // Ink
  ink: "#141412",            // primary near-black (numbers, headlines)
  inkMuted: "#6C6C66",       // secondary labels
  inkFaint: "#A1A19B",       // tertiary meta / placeholders

  // Restrained accent (Hymn brand, used only for links & subtle emphasis)
  accent: colors.brandPrimary,
  accentSoft: colors.brandTertiary,

  // Muted status pills
  pillBg: "#EFEFE9",
  pillInk: "#3E3E38",
  pillWarnBg: "#F5EADD",
  pillWarnInk: "#8A6533",
  pillErrBg: "#F5E4DE",
  pillErrInk: "#8F4432",
  pillOkBg: "#E6EDE3",
  pillOkInk: "#4A6F52",
  pillInfoBg: "#E4EAEE",
  pillInfoInk: "#3F5A6C",

  // Positive / negative money
  positive: "#4A6F52",
  negative: "#B36B57",
  danger: "#A65646",
};

export const financeType = {
  // Big display faces — Georgia (already loaded via theme.ts)
  displayXL: {
    fontFamily: "Georgia",
    fontWeight: "700" as const,
    fontSize: 48,
    letterSpacing: -1.2,
    lineHeight: 52,
    color: financeColors.ink,
    ...(Platform.OS === "ios" ? { fontVariant: ["tabular-nums" as const] } : {}),
  },
  displayL: {
    fontFamily: "Georgia",
    fontWeight: "700" as const,
    fontSize: 36,
    letterSpacing: -0.8,
    lineHeight: 40,
    color: financeColors.ink,
    ...(Platform.OS === "ios" ? { fontVariant: ["tabular-nums" as const] } : {}),
  },
  displayM: {
    fontFamily: "Georgia",
    fontWeight: "700" as const,
    fontSize: 26,
    letterSpacing: -0.4,
    lineHeight: 30,
    color: financeColors.ink,
    ...(Platform.OS === "ios" ? { fontVariant: ["tabular-nums" as const] } : {}),
  },
  amount: {
    fontFamily: Platform.select({ ios: "System", android: "sans-serif-medium", default: "System" }),
    fontWeight: "600" as const,
    fontSize: 15,
    color: financeColors.ink,
    ...(Platform.OS === "ios" ? { fontVariant: ["tabular-nums" as const] } : {}),
  },
  amountLg: {
    fontFamily: Platform.select({ ios: "System", android: "sans-serif-medium", default: "System" }),
    fontWeight: "700" as const,
    fontSize: 17,
    color: financeColors.ink,
    ...(Platform.OS === "ios" ? { fontVariant: ["tabular-nums" as const] } : {}),
  },
  rowLabel: {
    fontSize: 14,
    color: financeColors.ink,
    fontWeight: "500" as const,
  },
  rowMeta: {
    fontSize: 11.5,
    color: financeColors.inkMuted,
    marginTop: 2,
    lineHeight: 15,
  },
  sectionLabel: {
    fontSize: 10.5,
    color: financeColors.inkMuted,
    letterSpacing: 1.6,
    fontWeight: "600" as const,
    textTransform: "uppercase" as const,
  },
  screenTitle: {
    fontFamily: "Georgia",
    fontWeight: "700" as const,
    fontSize: 32,
    letterSpacing: -0.6,
    color: financeColors.ink,
  },
  subtitle: {
    fontSize: 12,
    color: financeColors.inkMuted,
    letterSpacing: 0.3,
    marginTop: 2,
  },
  body: {
    fontSize: 13.5,
    color: financeColors.ink,
    lineHeight: 20,
  },
  bodyMuted: {
    fontSize: 13,
    color: financeColors.inkMuted,
    lineHeight: 19,
  },
};

export const financeSpace = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, xxxl: 40 };
export const financeRadius = { sm: 8, md: 10, lg: 14, pill: 999 };
