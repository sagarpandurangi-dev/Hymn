import { useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { FoldAmount, FoldRow } from "@/src/components/finance/foldUi";
import { dateLabel, formatMoney } from "@/src/lib/finance/format";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";

const KIND_LABEL: Record<string, string> = {
  expense: "Spent",
  income: "Received",
  transfer: "Moved between your accounts",
  card_settlement: "Card bill paid",
  loan_payment: "Loan EMI",
  revaluation: "Market value change",
  investment: "Invested",
  redemption: "Taken out",
  refund: "Refund",
  borrowing: "Loan received",
};
export const kindLabel = (k?: string) => (k ? KIND_LABEL[k] ?? k.replace(/_/g, " ") : "");

type Activity = {
  id: string;
  detail?: "event" | "ledger" | string;
  kind?: string;
  description?: string;
  event_date: string;
  currency: string;
  direction: "inflow" | "outflow" | "transfer" | string;
  amount: string;
  source?: string;
};

const amountProps = (e: Activity) =>
  e.direction === "transfer"
    ? { value: `↔ ${formatMoney(e.amount)}`, tone: "muted" as const }
    : { value: formatMoney(e.amount), sign: (e.direction === "outflow" ? "-" : "+") as "-" | "+", tone: e.direction === "inflow" ? ("positive" as const) : ("ink" as const) };

/** Recent activity list: events open the event screen; money-book (ledger) rows open a read-only sheet. */
export default function RecentActivityList({ items }: { items: Activity[] }) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [sheet, setSheet] = useState<Activity | null>(null);

  return (
    <>
      {items.map((e, idx) => (
        <FoldRow
          key={e.id}
          first={idx === 0}
          label={e.description || kindLabel(e.kind) || "(no description)"}
          meta={[dateLabel(e.event_date), e.detail === "ledger" && e.description ? kindLabel(e.kind) : "", e.source].filter(Boolean).join(" · ")}
          right={<FoldAmount currency={e.currency} {...amountProps(e)} />}
          onPress={() => (e.detail === "ledger" ? setSheet(e) : router.push(`/finance/events/${e.id}`))}
          chevron
          testID={`event-${e.id}`}
        />
      ))}
      <Modal visible={!!sheet} transparent animationType="slide" onRequestClose={() => setSheet(null)}>
        <Pressable style={styles.backdrop} onPress={() => setSheet(null)} testID="ledger-sheet-backdrop" />
        {sheet ? (
          <View style={[styles.sheet, { paddingBottom: insets.bottom + financeSpace.lg }]} testID="ledger-sheet">
            <View style={styles.grabber} />
            <Text style={styles.title}>{sheet.description || kindLabel(sheet.kind)}</Text>
            <View style={styles.amountWrap}><FoldAmount currency={sheet.currency} size="lg" {...amountProps(sheet)} /></View>
            {[
              ["Date", dateLabel(sheet.event_date)],
              ["What", kindLabel(sheet.kind)],
              ["From", sheet.source || ""],
            ].filter(([, v]) => v).map(([k, v]) => (
              <View key={k} style={styles.row}>
                <Text style={styles.key}>{k}</Text>
                <Text style={styles.val} testID={`ledger-sheet-${k.toLowerCase()}`}>{v}</Text>
              </View>
            ))}
            <Text style={styles.note}>This entry lives in your money book.</Text>
            <Pressable style={styles.close} onPress={() => setSheet(null)} testID="ledger-sheet-close">
              <Text style={styles.closeText}>Close</Text>
            </Pressable>
          </View>
        ) : null}
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.3)" },
  sheet: { backgroundColor: financeColors.card, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.lg, gap: financeSpace.sm },
  grabber: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: financeColors.divider, marginBottom: financeSpace.sm },
  title: { fontSize: 18, fontWeight: "700", color: financeColors.ink },
  amountWrap: { alignItems: "flex-start", marginBottom: financeSpace.sm },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  key: { fontSize: 14, color: financeColors.inkMuted },
  val: { fontSize: 14, color: financeColors.ink, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  note: { fontSize: 12, color: financeColors.inkMuted, marginTop: financeSpace.sm },
  close: { minHeight: 48, borderRadius: 999, backgroundColor: financeColors.ink, alignItems: "center", justifyContent: "center", marginTop: financeSpace.md },
  closeText: { color: financeColors.card, fontSize: 15, fontWeight: "700" },
});
