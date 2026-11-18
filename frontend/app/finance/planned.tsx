import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { api, ApiError, PlannedItem, PlannedMonth } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import PlannedItemForm, { plannedMoney } from "@/src/components/finance/PlannedItemForm";
import { SwipeablePlannedRow } from "@/src/components/finance/PlannedRow";
import { confirmAction } from "@/src/lib/confirm";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { currentMonthIso, monthLabel } from "@/src/lib/finance/format";

const num = (v: unknown) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

export default function PlannedMoneyScreen() {
  const [items, setItems] = useState<PlannedItem[]>([]);
  const [months, setMonths] = useState<PlannedMonth[]>([]);
  const month = months[0] ?? null;
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PlannedItem | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [list, monthsRes] = await Promise.all([
        api.listPlannedMoney(true),
        api.plannedMoneyMonths(currentMonthIso(), 12).catch(() => null),
      ]);
      setItems(Array.isArray(list) ? list : []);
      setMonths(Array.isArray(monthsRes) ? monthsRes : monthsRes?.months ?? []);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  // Full-screen spinner only on the first load; later focuses refresh quietly.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        await load();
        if (alive) setLoading(false);
      })();
      return () => { alive = false; };
    }, [load]),
  );

  const defaultCurrency = items[0]?.currency || month?.currency || "INR";
  const cardCurrency = month?.currency || defaultCurrency;

  const closed = items.filter((i) => i.status === "done" || i.status === "cancelled");
  const open = items.filter((i) => i.status !== "done" && i.status !== "cancelled");
  const sure = open.filter((i) => i.certainty !== "maybe");
  const recurring = sure.filter((i) => i.repeat !== "once");
  const oneOffs = sure
    .filter((i) => i.repeat === "once")
    .sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  const maybes = open.filter((i) => i.certainty === "maybe");

  const openNew = () => { setEditing(null); setFormOpen(true); };
  const openItem = (it: PlannedItem) => { setEditing(it); setFormOpen(true); };

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };
  const markDone = (it: PlannedItem) => run(() => api.updatePlannedMoney(it.id, { status: "done" }));
  const cancelItem = (it: PlannedItem) => run(() => api.updatePlannedMoney(it.id, { status: "cancelled" }));
  const deleteItem = async (it: PlannedItem) => {
    const ok = await confirmAction("Delete this item?", `"${it.title}" will be removed from planned money.`, "Delete");
    if (ok) await run(() => api.deletePlannedMoney(it.id));
  };

  const group = (label: string, list: PlannedItem[], testID: string) =>
    list.length > 0 ? (
      <View style={styles.block} testID={testID}>
        <FoldSectionHeader label={label} hint={list.some((i) => i.editable !== false) ? "Swipe left for actions" : undefined} />
        <FoldCard>
          {list.map((it, idx) => (
            <SwipeablePlannedRow
              key={it.id}
              item={it}
              first={idx === 0}
              onPress={() => openItem(it)}
              onDone={() => markDone(it)}
              onCancel={() => cancelItem(it)}
              onDelete={() => deleteItem(it)}
            />
          ))}
        </FoldCard>
      </View>
    ) : null;

  const money = (v: unknown) => plannedMoney(cardCurrency, String(v ?? 0));

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader
        title="Planned money"
        subtitle="What's coming in and going out"
        right={
          <Pressable onPress={openNew} hitSlop={8} style={styles.addBtn} testID="planned-add-button">
            <Text style={styles.addText}>+ Add</Text>
          </Pressable>
        }
      />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={financeColors.ink} />}
        >
          {error ? <Text style={styles.error} testID="planned-error">{error}</Text> : null}

          {month ? (
            <View style={styles.block} testID="planned-month-card">
              <FoldSectionHeader label="This month" hint={monthLabel(month.month || currentMonthIso())} />
              <FoldCard>
                <FoldRow
                  first
                  label="Coming in"
                  meta={num(month.maybe_in) ? `Maybe +${money(month.maybe_in)}` : undefined}
                  right={<FoldAmount value={money(month.income)} tone="positive" />}
                />
                <FoldRow
                  label="Going out"
                  meta={num(month.maybe_out) ? `Maybe −${money(month.maybe_out)}` : undefined}
                  right={<FoldAmount value={money((num(month.spend) + num(month.set_aside)).toFixed(2))} />}
                />
                <FoldRow
                  label="To savings"
                  right={<FoldAmount value={money(month.moves)} />}
                />
              </FoldCard>
            </View>
          ) : null}

          {items.length === 0 && !error ? (
            <FoldCard><Text style={styles.empty}>Nothing planned yet. Tap + Add to plan income, bills or savings.</Text></FoldCard>
          ) : null}

          {group("Every month / year", recurring, "planned-group-recurring")}
          {group("Coming up", oneOffs, "planned-group-upcoming")}
          {group("Maybe", maybes, "planned-group-maybe")}
          {group("Done or cancelled", closed, "planned-group-closed")}

          {months.length > 0 ? (
            <View style={styles.block} testID="planned-next-12">
              <FoldSectionHeader label="Next 12 months" hint={cardCurrency} />
              <FoldCard>
                {months.map((m, idx) => (
                  <View key={m.month} style={[styles.monthRow, idx > 0 && styles.monthDivider]} testID={`planned-month-${m.month}`}>
                    <Text style={styles.monthName}>{monthLabel(m.month)}</Text>
                    <View style={styles.monthGrid}>
                      <Text style={styles.cell}>In <Text style={styles.cellIn}>{money(m.income)}</Text></Text>
                      <Text style={styles.cell}>Out <Text style={styles.cellVal}>{money(m.spend)}</Text></Text>
                      <Text style={styles.cell}>To savings/investments <Text style={styles.cellVal}>{money(m.moves)}</Text></Text>
                      <Text style={styles.cell}>Set aside <Text style={styles.cellVal}>{money(m.set_aside)}</Text></Text>
                      {num(m.maybe_in) ? <Text style={styles.maybe}>Maybe in {money(m.maybe_in)}</Text> : null}
                      {num(m.maybe_out) ? <Text style={styles.maybe}>Maybe out {money(m.maybe_out)}</Text> : null}
                    </View>
                  </View>
                ))}
              </FoldCard>
            </View>
          ) : null}
        </ScrollView>
      )}

      <PlannedItemForm
        visible={formOpen}
        item={editing}
        defaultCurrency={defaultCurrency}
        onClose={() => setFormOpen(false)}
        onSaved={async () => { setFormOpen(false); await load(); }}
      />
    </SafeAreaView>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  block: { gap: financeSpace.sm },
  error: { fontSize: 13, color: financeColors.negative },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  addBtn: { minHeight: 36, paddingHorizontal: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, justifyContent: "center" },
  addText: { fontSize: 13, fontWeight: "700", color: financeColors.ink },
  monthRow: { paddingHorizontal: financeSpace.lg, paddingVertical: financeSpace.md, gap: 4 },
  monthDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  monthName: { fontSize: 14, fontWeight: "700", color: financeColors.ink },
  monthGrid: { flexDirection: "row", flexWrap: "wrap", columnGap: financeSpace.md, rowGap: 2 },
  cell: { fontSize: 12, color: financeColors.inkMuted },
  cellIn: { fontSize: 12, fontWeight: "700", color: financeColors.positive },
  cellVal: { fontSize: 12, fontWeight: "700", color: financeColors.ink },
  maybe: { fontSize: 12, color: financeColors.inkMuted, fontStyle: "italic" },
});
