import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import DraggableFlatList, { RenderItemParams, ScaleDecorator } from "react-native-draggable-flatlist";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

// ─────────────────────────────── Types ────────────────────────────────
type GoalMeta = {
  id: string; title: string; notes: string; deadline: string;
  status: string; richness_score: number;
  outcome_count: number; task_count: number; checkins_count: number;
};

type OutcomePayload = {
  id: string; title: string; target_value?: string; unit?: string;
  deadline?: string; notes?: string;
  source_goal_id: string; source_goal_title: string;
  attached_tasks: { id: string; title: string; status: string; due_date?: string }[];
};

type OutcomeRule = {
  outcome_id: string;
  action: "keep" | "nest" | "delete";
  parent_outcome_id?: string | null;
  reason?: string;
};

type ConflictLine = { type: string; detail: string };

type Preview = {
  survivor_id: string;
  goals: GoalMeta[];
  outcomes: OutcomePayload[];
  outcome_rules: OutcomeRule[];
  duplicates: string[][];
  capacity_snapshot: {
    committed_hours_per_week: number;
    free_hours_per_week_estimate: number;
    active_goals: number;
    active_projects: number;
    open_tasks: number;
  };
  capacity_conflicts: ConflictLine[];
};

type Tradeoff = {
  kind: "goal" | "project" | "task";
  id: string;
  title: string;
  action: "postpone" | "cancel";
  new_due_date?: string;
};

// ─────────────────────────────── Screen ───────────────────────────────
export default function GoalsMergeWizardScreen() {
  const router = useRouter();
  const { ids } = useLocalSearchParams<{ ids: string }>();
  const goalIds = useMemo(() => (ids || "").split(",").filter(Boolean), [ids]);

  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [survivor, setSurvivor] = useState<string>("");
  // Flat ordered list of outcomes; each rule tracks action + parent.
  const [outcomes, setOutcomes] = useState<OutcomePayload[]>([]);
  const [rules, setRules] = useState<Record<string, OutcomeRule>>({});
  const [duplicatesApproved, setDuplicatesApproved] = useState<Set<string>>(new Set());
  const [tradeoffs, setTradeoffs] = useState<Tradeoff[]>([]);
  const [nestPickerFor, setNestPickerFor] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [portfolioForTradeoffs, setPortfolioForTradeoffs] = useState<{ goals: any[]; projects: any[]; tasks: any[] } | null>(null);
  const [tradeoffPickerOpen, setTradeoffPickerOpen] = useState(false);

  const load = useCallback(async () => {
    if (goalIds.length < 2) { setError("Pick at least 2 goals to merge."); setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const p = (await api.mergePreview(goalIds)) as Preview;
      setPreview(p);
      setSurvivor(p.survivor_id);
      setOutcomes(p.outcomes);
      const byId: Record<string, OutcomeRule> = {};
      for (const r of p.outcome_rules) byId[r.outcome_id] = r;
      setRules(byId);
      // Auto-check the LLM-recommended duplicates (delete action).
      const dupApprove = new Set<string>();
      for (const r of p.outcome_rules) if (r.action === "delete") dupApprove.add(r.outcome_id);
      setDuplicatesApproved(dupApprove);
    } catch (e: any) {
      setError(e?.message || "Could not load the merge preview.");
    } finally { setLoading(false); }
  }, [goalIds]);

  useEffect(() => { load(); }, [load]);

  const setAction = (outcomeId: string, action: "keep" | "nest" | "delete", parent?: string | null) => {
    setRules((prev) => ({
      ...prev,
      [outcomeId]: { outcome_id: outcomeId, action, parent_outcome_id: parent ?? null },
    }));
    setDuplicatesApproved((prev) => {
      const nx = new Set(prev);
      if (action === "delete") nx.add(outcomeId); else nx.delete(outcomeId);
      return nx;
    });
  };

  const openTradeoffs = useCallback(async () => {
    setTradeoffPickerOpen(true);
    if (portfolioForTradeoffs) return;
    try {
      const [gs, ps, ts] = await Promise.all([
        api.listGoals(),
        api.listProjects(),
        api.listTasks({ includeCompleted: false }),
      ]);
      setPortfolioForTradeoffs({ goals: gs as any[], projects: ps as any[], tasks: ts as any[] });
    } catch { /* noop */ }
  }, [portfolioForTradeoffs]);

  const addTradeoff = (kind: Tradeoff["kind"], id: string, title: string, action: "postpone" | "cancel", new_due_date?: string) => {
    setTradeoffs((prev) => [...prev.filter((t) => !(t.kind === kind && t.id === id)),
                            { kind, id, title, action, new_due_date }]);
  };

  const removeTradeoff = (kind: Tradeoff["kind"], id: string) => {
    setTradeoffs((prev) => prev.filter((t) => !(t.kind === kind && t.id === id)));
  };

  const hasConflict = !!(preview && preview.capacity_conflicts.length > 0);
  const canApply = preview !== null && (!hasConflict || tradeoffs.length > 0);

  const apply = async () => {
    if (!preview || !canApply || applying) return;
    setApplying(true); setApplyError(null);
    try {
      const outcome_rules = Object.values(rules).map((r) => ({
        outcome_id: r.outcome_id,
        action: r.action,
        parent_outcome_id: r.action === "nest" ? (r.parent_outcome_id || null) : null,
      }));
      const res = await api.mergeApply({
        goal_ids: goalIds,
        survivor_id: survivor,
        outcome_rules,
        delete_duplicate_ids: Array.from(duplicatesApproved),
        tradeoffs: tradeoffs.map((t) => ({ kind: t.kind, id: t.id, action: t.action, new_due_date: t.new_due_date })),
      });
      router.replace(`/goals/${res.survivor_id}`);
    } catch (e: any) {
      setApplyError(e?.message || "Merge failed.");
    } finally { setApplying(false); }
  };

  // Draggable list item.
  const renderItem = ({ item, drag, isActive }: RenderItemParams<OutcomePayload>) => {
    const rule = rules[item.id] || { outcome_id: item.id, action: "keep", parent_outcome_id: null };
    const parentTitle = rule.parent_outcome_id
      ? outcomes.find((o) => o.id === rule.parent_outcome_id)?.title
      : null;
    const isSurvivorGoal = item.source_goal_id === survivor;
    const dupBadge = preview?.duplicates.some((grp) => grp.includes(item.id)) ? "DUPLICATE?" : null;
    return (
      <ScaleDecorator>
        <Pressable
          onLongPress={drag}
          delayLongPress={150}
          disabled={isActive}
          style={[
            styles.outcomeCard,
            isActive && styles.outcomeCardActive,
            rule.action === "delete" && styles.outcomeCardDelete,
            rule.action === "nest" && styles.outcomeCardNested,
          ]}
          testID={`merge-outcome-${item.id}`}
        >
          <View style={styles.outcomeTop}>
            <Ionicons name="reorder-three" size={18} color={colors.onSurfaceTertiary} />
            <Text style={styles.outcomeSource} numberOfLines={1}>
              {isSurvivorGoal ? "SURVIVOR" : "MERGE"} · {item.source_goal_title || "—"}
            </Text>
            {dupBadge ? (
              <View style={styles.dupBadge}>
                <Text style={styles.dupBadgeText}>{dupBadge}</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.outcomeTitle} numberOfLines={2}>{item.title || "(untitled)"}</Text>
          {item.target_value || item.deadline || item.attached_tasks.length ? (
            <Text style={styles.outcomeMeta}>
              {item.target_value ? `${item.target_value}${item.unit ? ` ${item.unit}` : ""}` : ""}
              {item.deadline ? `${item.target_value ? " · " : ""}by ${item.deadline}` : ""}
              {item.attached_tasks.length ? `${item.target_value || item.deadline ? " · " : ""}${item.attached_tasks.length} task${item.attached_tasks.length !== 1 ? "s" : ""}` : ""}
            </Text>
          ) : null}
          {rule.action === "nest" && parentTitle ? (
            <Text style={styles.nestedNote}>↳ nested under: {parentTitle}</Text>
          ) : null}
          <View style={styles.actionRow}>
            <ActionChip
              icon="checkmark-outline" label="Keep"
              active={rule.action === "keep"}
              onPress={() => setAction(item.id, "keep")}
              testID={`merge-action-keep-${item.id}`}
            />
            <ActionChip
              icon="git-network-outline" label={rule.action === "nest" ? "Nested" : "Nest under…"}
              active={rule.action === "nest"}
              onPress={() => setNestPickerFor(item.id)}
              testID={`merge-action-nest-${item.id}`}
            />
            <ActionChip
              icon="trash-outline" label="Delete" danger
              active={rule.action === "delete"}
              onPress={() => setAction(item.id, "delete")}
              testID={`merge-action-delete-${item.id}`}
            />
          </View>
        </Pressable>
      </ScaleDecorator>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <GestureHandlerRootView style={styles.flex}>
        {/* Header */}
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} testID="merge-back" hitSlop={12}>
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, marginLeft: spacing.md }}>
            <Text style={styles.headerLabel}>MERGE GOALS</Text>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {goalIds.length} goals · {preview?.outcomes.length || 0} outcomes
            </Text>
          </View>
          <Pressable
            onPress={apply}
            disabled={!canApply || applying}
            style={[styles.applyBtn, (!canApply || applying) && { opacity: 0.4 }]}
            testID="merge-apply"
          >
            {applying ? (
              <ActivityIndicator color={colors.onBrandPrimary} size="small" />
            ) : (
              <Text style={styles.applyBtnText}>Apply</Text>
            )}
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
        ) : error ? (
          <View style={styles.center}><Text style={styles.errorText}>{error}</Text></View>
        ) : preview ? (
          <>
            {/* Survivor picker */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>SURVIVOR GOAL</Text>
              <Text style={styles.sectionHint}>Hymn picked the richest by metadata; you can override.</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.survivorRow}>
                {preview.goals.map((g) => (
                  <Pressable
                    key={g.id}
                    onPress={() => setSurvivor(g.id)}
                    style={[styles.survivorCard, survivor === g.id && styles.survivorCardSelected]}
                    testID={`merge-survivor-${g.id}`}
                  >
                    <Text style={styles.survivorTitle} numberOfLines={2}>{g.title}</Text>
                    <Text style={styles.survivorMeta}>
                      {g.outcome_count}o · {g.task_count}t · {g.checkins_count}ci · score {g.richness_score}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            </View>

            {/* Capacity conflicts */}
            {preview.capacity_conflicts.length > 0 ? (
              <View style={styles.conflictBox}>
                <View style={styles.conflictHeader}>
                  <Ionicons name="warning" size={16} color={colors.warning} />
                  <Text style={styles.conflictTitle}>
                    Merger requires portfolio rebalancing
                  </Text>
                </View>
                {preview.capacity_conflicts.map((c, i) => (
                  <Text key={i} style={styles.conflictDetail}>• {c.detail}</Text>
                ))}
                <View style={styles.tradeoffList}>
                  {tradeoffs.map((t) => (
                    <View key={`${t.kind}-${t.id}`} style={styles.tradeoffPill}>
                      <Text style={styles.tradeoffText}>
                        {t.action === "postpone" ? "Postpone" : "Cancel"} · {t.title}
                        {t.new_due_date ? ` → ${t.new_due_date}` : ""}
                      </Text>
                      <Pressable onPress={() => removeTradeoff(t.kind, t.id)} hitSlop={6}>
                        <Ionicons name="close-circle" size={14} color={colors.onSurfaceSecondary} />
                      </Pressable>
                    </View>
                  ))}
                </View>
                <Pressable onPress={openTradeoffs} style={styles.addTradeoffBtn} testID="merge-add-tradeoff">
                  <Ionicons name="add-circle-outline" size={16} color={colors.brandPrimary} />
                  <Text style={styles.addTradeoffText}>Postpone or cancel something</Text>
                </Pressable>
              </View>
            ) : null}

            {/* Draggable outcome list */}
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>OUTCOMES ({outcomes.length})</Text>
              <Text style={styles.sectionHint}>Long-press to drag, tap Nest under to nest.</Text>
            </View>
            <View style={styles.dragArea}>
              <DraggableFlatList
                data={outcomes}
                keyExtractor={(o) => o.id}
                onDragEnd={({ data }) => setOutcomes(data)}
                renderItem={renderItem}
                contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: spacing.xxxl }}
                activationDistance={12}
              />
            </View>

            {applyError ? <Text style={styles.errorText}>{applyError}</Text> : null}
          </>
        ) : null}

        {/* Nest picker modal */}
        <Modal
          visible={nestPickerFor !== null}
          transparent
          animationType="fade"
          onRequestClose={() => setNestPickerFor(null)}
        >
          <Pressable style={styles.modalBackdrop} onPress={() => setNestPickerFor(null)}>
            <Pressable style={styles.modalCard} onPress={(e) => e.stopPropagation()}>
              <Text style={styles.modalTitle}>Nest this outcome under…</Text>
              <ScrollView style={{ maxHeight: 380 }}>
                {outcomes
                  .filter((o) => o.id !== nestPickerFor && (rules[o.id]?.action ?? "keep") !== "delete")
                  .map((o) => (
                    <Pressable
                      key={o.id}
                      style={styles.pickerRow}
                      onPress={() => {
                        if (nestPickerFor) setAction(nestPickerFor, "nest", o.id);
                        setNestPickerFor(null);
                      }}
                      testID={`merge-nest-target-${o.id}`}
                    >
                      <Text style={styles.pickerTitle} numberOfLines={2}>{o.title}</Text>
                      <Text style={styles.pickerMeta}>{o.source_goal_title}</Text>
                    </Pressable>
                  ))}
              </ScrollView>
              <Pressable onPress={() => setNestPickerFor(null)} style={styles.modalCancel}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
            </Pressable>
          </Pressable>
        </Modal>

        {/* Tradeoff picker modal */}
        <TradeoffPickerModal
          visible={tradeoffPickerOpen}
          portfolio={portfolioForTradeoffs}
          onCancel={() => setTradeoffPickerOpen(false)}
          onPick={(t) => {
            addTradeoff(t.kind, t.id, t.title, t.action, t.new_due_date);
            setTradeoffPickerOpen(false);
          }}
        />
      </GestureHandlerRootView>
    </SafeAreaView>
  );
}

// ─────────────────────── Sub-components ─────────────────────────────
function ActionChip({
  icon, label, active, onPress, danger, testID,
}: { icon: any; label: string; active: boolean; onPress: () => void; danger?: boolean; testID?: string }) {
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.chip,
        active && (danger ? styles.chipActiveDanger : styles.chipActive),
      ]}
      testID={testID}
    >
      <Ionicons
        name={icon}
        size={14}
        color={active ? (danger ? colors.onError : colors.onBrandPrimary) : (danger ? colors.error : colors.onSurface)}
      />
      <Text style={[
        styles.chipText,
        active && { color: danger ? colors.onError : colors.onBrandPrimary },
      ]}>{label}</Text>
    </Pressable>
  );
}

function TradeoffPickerModal({
  visible, portfolio, onCancel, onPick,
}: {
  visible: boolean;
  portfolio: { goals: any[]; projects: any[]; tasks: any[] } | null;
  onCancel: () => void;
  onPick: (t: { kind: "goal" | "project" | "task"; id: string; title: string; action: "postpone" | "cancel"; new_due_date?: string }) => void;
}) {
  const [customDate, setCustomDate] = useState<string>("");
  const [selected, setSelected] = useState<{ kind: "goal" | "project" | "task"; id: string; title: string; commitment_type?: string } | null>(null);
  const [action, setAction] = useState<"postpone" | "cancel">("postpone");

  const items = useMemo(() => {
    if (!portfolio) return [];
    const g = (portfolio.goals || [])
      .filter((x: any) => x.status === "active" && (x.commitment_type || "postponable") !== "exclusive")
      .map((x: any) => ({ kind: "goal" as const, id: x.id, title: x.title, commitment_type: x.commitment_type }));
    const p = (portfolio.projects || [])
      .filter((x: any) => x.status === "active" && (x.commitment_type || "postponable") !== "exclusive")
      .map((x: any) => ({ kind: "project" as const, id: x.id, title: x.title, commitment_type: x.commitment_type }));
    const t = (portfolio.tasks || [])
      .filter((x: any) => (x.status !== "done" && x.status !== "cancelled") && (x.commitment_type || "postponable") !== "exclusive")
      .slice(0, 30)
      .map((x: any) => ({ kind: "task" as const, id: x.id, title: x.title, commitment_type: x.commitment_type }));
    return [...g, ...p, ...t];
  }, [portfolio]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.modalBackdrop} onPress={onCancel}>
        <Pressable style={styles.modalCardLg} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.modalTitle}>Postpone or cancel something</Text>
          {!portfolio ? (
            <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: spacing.md }} />
          ) : (
            <>
              <ScrollView style={{ maxHeight: 260 }}>
                {items.map((it) => (
                  <Pressable
                    key={`${it.kind}-${it.id}`}
                    style={[styles.pickerRow, selected?.id === it.id && { backgroundColor: colors.brandPrimary + "20" }]}
                    onPress={() => setSelected(it)}
                    testID={`merge-tradeoff-pick-${it.id}`}
                  >
                    <Text style={styles.pickerMeta}>{it.kind.toUpperCase()}</Text>
                    <Text style={styles.pickerTitle} numberOfLines={2}>{it.title}</Text>
                  </Pressable>
                ))}
                {items.length === 0 ? <Text style={styles.helpText}>No postponable items in your portfolio.</Text> : null}
              </ScrollView>
              {selected ? (
                <View style={{ marginTop: spacing.md, gap: spacing.sm }}>
                  <View style={{ flexDirection: "row", gap: spacing.sm }}>
                    <ActionChip icon="calendar-outline" label="Postpone" active={action === "postpone"} onPress={() => setAction("postpone")} testID="merge-tradeoff-action-postpone" />
                    <ActionChip icon="close-circle-outline" label="Cancel" danger active={action === "cancel"} onPress={() => setAction("cancel")} testID="merge-tradeoff-action-cancel" />
                  </View>
                  {action === "postpone" ? (
                    <TextInput
                      value={customDate}
                      onChangeText={setCustomDate}
                      placeholder="Postpone until (YYYY-MM-DD)"
                      placeholderTextColor={colors.onSurfaceTertiary}
                      style={styles.dateInput}
                      testID="merge-tradeoff-date-input"
                    />
                  ) : null}
                  <Pressable
                    onPress={() => {
                      if (!selected) return;
                      if (action === "postpone" && !/^\d{4}-\d{2}-\d{2}$/.test(customDate)) return;
                      onPick({ kind: selected.kind, id: selected.id, title: selected.title, action, new_due_date: action === "postpone" ? customDate : undefined });
                      setSelected(null); setCustomDate("");
                    }}
                    style={styles.modalConfirm}
                    testID="merge-tradeoff-confirm"
                  >
                    <Text style={styles.modalConfirmText}>Add tradeoff</Text>
                  </Pressable>
                </View>
              ) : null}
            </>
          )}
          <Pressable onPress={onCancel} style={styles.modalCancel}>
            <Text style={styles.modalCancelText}>Done</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderStrong,
  },
  headerLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: colors.onSurface, fontWeight: "600" },
  applyBtn: { backgroundColor: colors.brandPrimary, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill },
  applyBtnText: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 13 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  errorText: { color: colors.error, textAlign: "center", padding: spacing.md, fontSize: 13 },
  section: { paddingHorizontal: spacing.xl, marginTop: spacing.md },
  sectionLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5, fontWeight: "600" },
  sectionHint: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  survivorRow: { gap: spacing.sm, paddingVertical: spacing.sm, paddingRight: spacing.md },
  survivorCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md,
    borderWidth: 2, borderColor: "transparent", minWidth: 180, maxWidth: 240,
  },
  survivorCardSelected: { borderColor: colors.brandPrimary },
  survivorTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  survivorMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4 },
  conflictBox: {
    marginHorizontal: spacing.xl, marginTop: spacing.md,
    backgroundColor: colors.warning + "18", borderRadius: radius.md,
    padding: spacing.md, borderLeftWidth: 3, borderLeftColor: colors.warning,
  },
  conflictHeader: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  conflictTitle: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  conflictDetail: { color: colors.onSurfaceSecondary, fontSize: 12, lineHeight: 17, marginTop: 2 },
  tradeoffList: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  tradeoffPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.surface, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill,
  },
  tradeoffText: { fontSize: 12, color: colors.onSurface },
  addTradeoffBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.sm },
  addTradeoffText: { color: colors.brandPrimary, fontSize: 13, fontWeight: "500" },
  dragArea: { flex: 1 },
  outcomeCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  outcomeCardActive: { backgroundColor: colors.brandPrimary + "18" },
  outcomeCardDelete: { opacity: 0.55, borderWidth: 1, borderColor: colors.error, borderStyle: "dashed" },
  outcomeCardNested: { borderLeftWidth: 3, borderLeftColor: colors.brandPrimary, marginLeft: 20 },
  outcomeTop: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  outcomeSource: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1, flex: 1 },
  dupBadge: { backgroundColor: colors.warning + "22", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  dupBadgeText: { fontSize: 9, color: colors.warning, fontWeight: "700", letterSpacing: 0.5 },
  outcomeTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "600", lineHeight: 20 },
  outcomeMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  nestedNote: { fontSize: 11, color: colors.brandPrimary, marginTop: 4, fontStyle: "italic" },
  actionRow: { flexDirection: "row", gap: 6, marginTop: spacing.sm, flexWrap: "wrap" },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.sm, paddingVertical: 6,
    borderRadius: radius.pill, backgroundColor: colors.brandTertiary,
  },
  chipActive: { backgroundColor: colors.brandPrimary },
  chipActiveDanger: { backgroundColor: colors.error },
  chipText: { fontSize: 12, color: colors.onSurface },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: spacing.xl },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.md },
  modalCardLg: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.md, maxHeight: "80%" },
  modalTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: colors.onSurface, fontWeight: "600" },
  pickerRow: {
    padding: spacing.md, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderStrong,
  },
  pickerTitle: { fontSize: 14, color: colors.onSurface, marginTop: 2 },
  pickerMeta: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1 },
  helpText: { fontSize: 12, color: colors.onSurfaceSecondary, textAlign: "center", marginTop: spacing.md },
  dateInput: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: 14,
  },
  modalConfirm: { backgroundColor: colors.brandPrimary, padding: spacing.md, borderRadius: radius.pill, alignItems: "center" },
  modalConfirmText: { color: colors.onBrandPrimary, fontWeight: "600" },
  modalCancel: { paddingVertical: spacing.sm, alignItems: "center" },
  modalCancelText: { color: colors.onSurfaceSecondary, fontSize: 13 },
});
