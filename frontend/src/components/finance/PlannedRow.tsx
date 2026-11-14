import { StyleSheet, Text, View } from "react-native";
import { PlannedItem } from "@/src/lib/api";
import { FoldAmount, FoldPill, FoldRow } from "@/src/components/finance/foldUi";
import { financeType } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";
import { plannedWhen } from "@/src/components/finance/PlannedItemForm";

/** One planned-money row: title, +/− amount, Monthly / Yearly / date, Set aside tag. */
export default function PlannedRow({ item, first, onPress }: { item: PlannedItem; first?: boolean; onPress: () => void }) {
  const isIn = item.direction === "in";
  return (
    <FoldRow
      first={first}
      onPress={onPress}
      chevron
      testID={`planned-row-${item.id}`}
      label={
        <View style={styles.labelRow}>
          <Text style={[financeType.rowLabel, styles.title]} numberOfLines={1}>{item.title}</Text>
          {item.set_aside ? <FoldPill label="Set aside" tone="info" size="xs" /> : null}
          {item.status === "done" ? <FoldPill label="Done" tone="ok" size="xs" /> : null}
        </View>
      }
      meta={plannedWhen(item)}
      right={
        <FoldAmount
          currency={item.currency}
          value={`${isIn ? "+" : "−"}${formatMoney(String(item.amount))}`}
          tone={isIn ? "positive" : "ink"}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  labelRow: { flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" },
  title: { maxWidth: 200 },
});
