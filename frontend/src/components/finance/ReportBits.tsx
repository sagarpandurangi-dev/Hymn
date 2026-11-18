import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { formatINR, formatMoney } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

/** ₹ with Indian grouping for INR; "USD 1,234.00" style otherwise. Negatives in brackets, statement style. */
export const reportMoney = (currency: string | undefined, v: unknown): string => {
  const s = String(v ?? 0).trim();
  const neg = s.startsWith("-") && Number(s) !== 0;
  const abs = neg ? s.slice(1) : s;
  const out = !currency || currency === "INR" ? formatINR(abs) : `${currency} ${formatMoney(abs)}`;
  return neg ? `(${out})` : out;
};

// The report groups/lines come from the server; read their common field names defensively.
export const labelOf = (x: any): string => String(x?.label ?? x?.name ?? x?.title ?? x?.category ?? x?.key ?? "");
export const amountOf = (x: any): string => String(x?.amount ?? x?.total ?? x?.net ?? x?.balance ?? x?.value ?? "0");
export const linesOf = (x: any): any[] => {
  for (const k of ["lines", "categories", "items", "accounts", "children", "groups"]) {
    if (Array.isArray(x?.[k])) return x[k];
  }
  return [];
};
export const entryText = (e: any): string => String(e?.description ?? e?.note ?? e?.merchant ?? e?.title ?? e?.payee ?? "—");

/** First currency block from a report response (arrays per currency, or a single object). */
export const firstBlock = (res: any): any => (Array.isArray(res) ? res[0] : res?.by_currency?.[0] ?? res) ?? null;

type LineProps = {
  label: string;
  amounts: string[];
  bold?: boolean;
  indent?: boolean;
  topRule?: boolean;
  doubleRule?: boolean;
  muted?: boolean;
  onPress?: () => void;
  expanded?: boolean;
  testID?: string;
};

/** One statement line: label, then right-aligned amount(s). Multi-column lines put the label on its own row. */
export function StatementLine({ label, amounts, bold, indent, topRule, doubleRule, muted, onPress, expanded, testID }: LineProps) {
  const multi = amounts.length > 1;
  const labelEl = (
    <View style={[styles.labelWrap, indent && { paddingLeft: financeSpace.lg }]}>
      {onPress ? (
        <Ionicons name={expanded ? "chevron-down" : "chevron-forward"} size={12} color={financeColors.inkMuted} />
      ) : null}
      <Text style={[styles.label, bold && styles.bold, muted && styles.muted]} numberOfLines={2}>{label}</Text>
    </View>
  );
  const amountEls = amounts.map((a, i) => (
    <Text key={i} style={[styles.amount, multi && styles.amountCol, bold && styles.bold, muted && styles.muted]} numberOfLines={1} adjustsFontSizeToFit>
      {a}
    </Text>
  ));
  const body = multi ? (
    <View style={[styles.multi, topRule && styles.topRule, doubleRule && styles.doubleRule]} testID={testID}>
      {labelEl}
      <View style={styles.amountRow}>{amountEls}</View>
    </View>
  ) : (
    <View style={[styles.line, topRule && styles.topRule, doubleRule && styles.doubleRule]} testID={testID}>
      {labelEl}
      {amountEls}
    </View>
  );
  return onPress ? <Pressable onPress={onPress} accessibilityRole="button">{body}</Pressable> : body;
}

export function StatementHeading({ text, columns }: { text: string; columns?: string[] }) {
  return (
    <View style={[styles.multiHead, styles.heading]}>
      <Text style={styles.headingText}>{text}</Text>
      {columns?.length ? (
        <View style={styles.amountRow}>
          {columns.map((c) => <Text key={c} style={[styles.colHead, styles.amountCol]}>{c}</Text>)}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  line: { flexDirection: "row", alignItems: "center", paddingVertical: 8, paddingHorizontal: financeSpace.lg, gap: financeSpace.sm, minHeight: 44 },
  multi: { paddingVertical: 8, paddingHorizontal: financeSpace.lg, gap: 2, minHeight: 44 },
  multiHead: { paddingHorizontal: financeSpace.lg, gap: 4 },
  amountRow: { flexDirection: "row", gap: financeSpace.sm },
  labelWrap: { flex: 1, flexDirection: "row", alignItems: "center", gap: 4 },
  label: { fontSize: 14, color: financeColors.ink, flexShrink: 1 },
  amount: { fontSize: 14, color: financeColors.ink, textAlign: "right", fontVariant: ["tabular-nums"] },
  amountCol: { flex: 1, minWidth: 0 },
  bold: { fontWeight: "700" },
  muted: { color: financeColors.inkMuted },
  topRule: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  doubleRule: { borderTopWidth: 2, borderTopColor: financeColors.ink },
  heading: { paddingTop: financeSpace.md, paddingBottom: 4 },
  headingText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.8, color: financeColors.inkMuted },
  colHead: { fontSize: 11, fontWeight: "700", color: financeColors.inkMuted, textAlign: "right" },
});
