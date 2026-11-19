/**
 * Shared bits for "Things I own & owe" (life objects). Display only —
 * every number comes from the server.
 */
import { StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { FoldCard } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

export const LIFE_TYPES = [
  { code: "asset", label: "Asset" },
  { code: "liability", label: "Liability" },
  { code: "venture", label: "Venture" },
] as const;

export const LIFE_KINDS = [
  { code: "car", label: "Car" },
  { code: "bike", label: "Bike" },
  { code: "house", label: "House" },
  { code: "phone", label: "Phone" },
  { code: "credit_card", label: "Credit card" },
  { code: "loan", label: "Loan" },
  { code: "business", label: "Business" },
  { code: "other", label: "Other" },
];

export const LOAN_ACCOUNT_TYPES = ["credit_card", "personal_loan", "home_loan", "vehicle_loan", "other_liability"];

export const kindLabel = (k?: string) => LIFE_KINDS.find((x) => x.code === k)?.label ?? (k ? k.replace(/_/g, " ") : "");
export const typeLabel = (t?: string) => LIFE_TYPES.find((x) => x.code === t)?.label ?? (t ?? "");

/** A loan is anything of type liability or kind loan / credit card. */
export const isLoan = (o: any) => o?.type === "liability" || o?.kind === "loan" || o?.kind === "credit_card";
export const isVehicle = (o: any) => o?.kind === "car" || o?.kind === "bike";

export const curOf = (o: any): string => o?.currency ?? o?.ltc?.currency ?? "INR";

/** "₹4.20 per km" — keeps two decimals for small per-unit costs. */
export const perUnitText = (currency: string, ltc: any): string => {
  if (ltc?.per_unit == null) return "";
  const n = Number(ltc.per_unit);
  const v = Number.isFinite(n) ? n.toFixed(2) : String(ltc.per_unit);
  const money = currency === "INR" ? `₹${v.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}` : reportMoney(currency, v);
  return ltc.unit ? `${money} per ${ltc.unit}` : money;
};

export const objectsOf = (res: any): any[] =>
  Array.isArray(res) ? res : res?.items ?? res?.life_objects ?? res?.objects ?? [];

export function PremiumCard({ text }: { text: string }) {
  return (
    <FoldCard testID="life-objects-premium">
      <View style={styles.pad}>
        <Ionicons name="sparkles-outline" size={20} color={financeColors.ink} />
        <Text style={styles.h}>Premium feature</Text>
        <Text style={styles.body}>{text}</Text>
      </View>
    </FoldCard>
  );
}

export const lifeStyles = StyleSheet.create({
  scroll: { padding: financeSpace.lg, paddingBottom: financeSpace.xxxl * 2, gap: financeSpace.lg },
  pad: { padding: financeSpace.lg, gap: financeSpace.sm },
  h: { fontSize: 16, fontWeight: "700", color: financeColors.ink },
  body: { fontSize: 14, lineHeight: 20, color: financeColors.inkMuted },
  label: { fontSize: 13, fontWeight: "600", color: financeColors.inkMuted, marginTop: financeSpace.sm },
  input: { minHeight: 48, borderWidth: 1, borderColor: financeColors.divider, borderRadius: 10, paddingHorizontal: financeSpace.md, fontSize: 15, color: financeColors.ink, backgroundColor: financeColors.card, justifyContent: "center" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm },
  chip: { minHeight: 40, paddingHorizontal: financeSpace.md, borderRadius: 999, borderWidth: 1, borderColor: financeColors.divider, alignItems: "center", justifyContent: "center", backgroundColor: financeColors.card },
  chipOn: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipText: { fontSize: 14, color: financeColors.ink, fontWeight: "600" },
  chipTextOn: { color: financeColors.card },
  primary: { minHeight: 50, borderRadius: 999, backgroundColor: financeColors.ink, alignItems: "center", justifyContent: "center" },
  primaryText: { color: financeColors.card, fontSize: 15, fontWeight: "700" },
  secondary: { minHeight: 48, borderRadius: 999, borderWidth: 1, borderColor: financeColors.divider, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8, backgroundColor: financeColors.card },
  secondaryText: { fontSize: 15, fontWeight: "600", color: financeColors.ink },
  error: { fontSize: 13, color: financeColors.negative },
  empty: { padding: financeSpace.lg, fontSize: 14, color: financeColors.inkMuted },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});

const styles = lifeStyles;
