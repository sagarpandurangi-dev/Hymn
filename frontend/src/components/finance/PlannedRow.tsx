import { useRef } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import ReanimatedSwipeable, { SwipeableMethods } from "react-native-gesture-handler/ReanimatedSwipeable";
import { PlannedItem } from "@/src/lib/api";
import { FoldAmount, FoldPill, FoldRow } from "@/src/components/finance/foldUi";
import { financeColors, financeType } from "@/src/lib/finance/theme";
import { plannedMoney, plannedSigned, plannedWhen } from "@/src/components/finance/PlannedItemForm";

const num = (v: unknown) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

/**
 * One planned-money row: title, +/− amount (in green), repeat, Maybe / Set aside tags,
 * what's left when part is done, and a lock for items owned by an older screen.
 */
export default function PlannedRow({ item, first, onPress }: { item: PlannedItem; first?: boolean; onPress: () => void }) {
  const isIn = item.direction === "in";
  const locked = item.editable === false;
  const done = num(item.done_amount);
  const partly = done > 0 && num(item.remaining_amount) > 0 && item.status !== "done";
  const meta = [
    plannedWhen(item),
    partly ? `${plannedMoney(item.currency, item.remaining_amount)} left` : "",
    locked ? "Edit on the old screen" : "",
  ].filter(Boolean).join(" · ");
  return (
    <FoldRow
      first={first}
      onPress={onPress}
      chevron={!locked}
      testID={`planned-row-${item.id}`}
      label={
        <View style={styles.labelRow}>
          {locked ? <Ionicons name="lock-closed-outline" size={12} color={financeColors.inkMuted} testID={`planned-lock-${item.id}`} /> : null}
          <Text style={[financeType.rowLabel, styles.title]} numberOfLines={1}>{item.title}</Text>
          {item.certainty === "maybe" ? <FoldPill label="Maybe" tone="neutral" size="xs" /> : null}
          {item.set_aside ? <FoldPill label="Set aside" tone="info" size="xs" /> : null}
          {item.status === "done" ? <FoldPill label="Done" tone="ok" size="xs" /> : null}
          {item.status === "cancelled" ? <FoldPill label="Cancelled" tone="neutral" size="xs" /> : null}
        </View>
      }
      meta={meta}
      right={
        <FoldAmount
          currency={item.currency === "INR" ? undefined : item.currency}
          value={plannedSigned(item)}
          tone={item.certainty === "maybe" ? "muted" : isIn ? "positive" : "ink"}
        />
      }
    />
  );
}

type SwipeProps = {
  item: PlannedItem;
  first?: boolean;
  onPress: () => void;
  onDone: () => void;
  onCancel: () => void;
  onDelete: () => void;
};

/** Planned row with swipe-left actions: Mark done, Cancel, Delete. Older (locked) items don't swipe. */
export function SwipeablePlannedRow({ item, first, onPress, onDone, onCancel, onDelete }: SwipeProps) {
  const ref = useRef<SwipeableMethods>(null);
  // A drag must not also count as a tap (web fires press after a mouse drag).
  const isOpen = useRef(false);
  const lastDrag = useRef(0);
  if (item.editable === false) return <PlannedRow item={item} first={first} onPress={onPress} />;

  const press = () => {
    if (Date.now() - lastDrag.current < 400) return;
    if (isOpen.current) { ref.current?.close(); return; }
    onPress();
  };

  const act = (fn: () => void) => () => { ref.current?.close(); fn(); };
  const actions = () => (
    <View style={styles.actions}>
      {item.status !== "done" ? (
        <Pressable style={[styles.action, { backgroundColor: financeColors.positive }]} onPress={act(onDone)} testID={`planned-swipe-done-${item.id}`}>
          <Ionicons name="checkmark" size={18} color={financeColors.card} />
          <Text style={styles.actionText}>Done</Text>
        </Pressable>
      ) : null}
      {item.status !== "cancelled" ? (
        <Pressable style={[styles.action, { backgroundColor: financeColors.inkMuted }]} onPress={act(onCancel)} testID={`planned-swipe-cancel-${item.id}`}>
          <Ionicons name="close" size={18} color={financeColors.card} />
          <Text style={styles.actionText}>Cancel</Text>
        </Pressable>
      ) : null}
      <Pressable style={[styles.action, { backgroundColor: financeColors.negative }]} onPress={act(onDelete)} testID={`planned-swipe-delete-${item.id}`}>
        <Ionicons name="trash-outline" size={18} color={financeColors.card} />
        <Text style={styles.actionText}>Delete</Text>
      </Pressable>
    </View>
  );

  return (
    <ReanimatedSwipeable
      ref={ref}
      friction={2}
      rightThreshold={40}
      overshootRight={false}
      renderRightActions={actions}
      onSwipeableOpenStartDrag={() => { lastDrag.current = Date.now(); }}
      onSwipeableCloseStartDrag={() => { lastDrag.current = Date.now(); }}
      onSwipeableWillOpen={() => { isOpen.current = true; lastDrag.current = Date.now(); }}
      onSwipeableClose={() => { isOpen.current = false; }}
    >
      <View style={{ backgroundColor: financeColors.card }}>
        <PlannedRow item={item} first={first} onPress={press} />
      </View>
    </ReanimatedSwipeable>
  );
}

const styles = StyleSheet.create({
  labelRow: { flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" },
  title: { maxWidth: 180 },
  actions: { flexDirection: "row" },
  action: { width: 72, alignItems: "center", justifyContent: "center", gap: 2 },
  actionText: { color: financeColors.card, fontSize: 12, fontWeight: "700" },
});
