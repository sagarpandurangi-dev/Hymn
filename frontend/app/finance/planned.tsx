import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { api, ApiError, PlannedItem, PlannedMonth } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldAmount, FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import PlannedItemForm from "@/src/components/finance/PlannedItemForm";
import PlannedRow from "@/src/components/finance/PlannedRow";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { currentMonthIso, formatMoney, monthLabel } from "@/src/lib/finance/format";

const num = (v: unknown) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

export default function PlannedMoneyScreen() {
  const [items, setItems] = useState<PlannedItem[]>([]);
  const [month, setMonth] = useState<PlannedMonth | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PlannedItem | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [list, months] = await Promise.all([
        api.listPlannedMoney(),
        api.plannedMoneyMonths(currentMonthIso(), 12).catch(() => null),
      ]);
      setItems(Array.isArray(list) ? list : []);
      const arr = Array.isArray(months) ? months : months?.months ?? [];
      setMonth(arr[0] ?? null);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        setLoading(true);
        await load();
        if (alive) setLoading(false);
      })();
      return () => { alive = false; };
    }, [load]),
  );

  const defaultCurrency = items[0]?.currency || month?.currency || "INR";
  const cardCurrency = month?.currency || defaultCurrency;

  const sure = items.filter((i) => i.certainty !== "maybe");
  const recurring = sure.filter((i) => i.repeat !== "once");
  const oneOffs = sure
    .filter((i) => i.repeat === "once")
    .sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  const maybes = items.filter((i) => i.certainty === "maybe");

  const openNew = () => { setEditing(null); setFormOpen(true); };
  const openItem = (it: PlannedItem) => { setEditing(it); setFormOpen(true); };

  const group = (label: string, list: PlannedItem[], testID: string) =>
    list.length > 0 ? (
      <View style={styles.block} testID={testID}>
        <FoldSectionHeader label={label} />
        <FoldCard>
          {list.map((it, idx) => <PlannedRow key={it.id} item={it} first={idx === 0} onPress={() => openItem(it)} />)}
        </FoldCard>
      </View>
    ) : null;

  return (
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
                  meta={num(month.maybe_in) ? `Maybe +${formatMoney(String(month.maybe_in))}` : undefined}
                  right={<FoldAmount currency={cardCurrency} value={formatMoney(String(month.income ?? 0))} tone="positive" />}
                />
                <FoldRow
                  label="Going out"
                  meta={num(month.maybe_out) ? `Maybe −${formatMoney(String(month.maybe_out))}` : undefined}
                  right={<FoldAmount currency={cardCurrency} value={formatMoney(String(num(month.spend) + num(month.set_aside)))} />}
                />
                <FoldRow
                  label="To savings"
                  right={<FoldAmount currency={cardCurrency} value={formatMoney(String(month.moves ?? 0))} />}
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
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  block: { gap: financeSpace.sm },
  error: { fontSize: 13, color: financeColors.negative },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  addBtn: { minHeight: 36, paddingHorizontal: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, justifyContent: "center" },
  addText: { fontSize: 13, fontWeight: "700", color: financeColors.ink },
});
