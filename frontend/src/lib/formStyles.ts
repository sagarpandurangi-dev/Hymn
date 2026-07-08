import { StyleSheet } from "react-native";
import { colors, radius, spacing, fonts } from "@/src/lib/theme";

export const formStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  titleInput: {
    fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface,
    paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  input: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface,
  },
  notes: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 120,
  },
  chipRow: { gap: spacing.sm, paddingRight: spacing.xl },
  chip: {
    flexShrink: 0, height: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center",
  },
  chipSelected: { backgroundColor: colors.brandPrimary },
  chipText: { color: colors.onBrandTertiary, fontSize: 13, fontWeight: "500" },
  chipTextSelected: { color: colors.onBrandPrimary },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, paddingTop: spacing.sm },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
  row: {
    flexDirection: "row", gap: spacing.md, alignItems: "center",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, marginBottom: spacing.sm,
  },
  rowTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
