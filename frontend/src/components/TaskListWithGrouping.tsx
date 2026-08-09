import React, { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import { api } from "@/src/lib/api";

export type TaskLike = {
  id: string;
  title: string;
  due_date: string;
  priority: string;
  status: string;
};

type Bucket = "today" | "week" | "month" | "later" | "no_date" | "done";

const BUCKET_LABEL: Record<Bucket, string> = {
  today: "Today",
  week: "This week",
  month: "This month",
  later: "Later",
  no_date: "No due date",
  done: "Completed",
};

function bucketOf(t: TaskLike, now: Date): Bucket {
  if (t.status === "done" || t.status === "cancelled") return "done";
  if (!t.due_date) return "no_date";
  const d = new Date(t.due_date + "T00:00:00");
  if (isNaN(d.getTime())) return "no_date";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfTomorrow = new Date(startOfToday.getTime() + 24 * 3600 * 1000);
  const startOfNextWeek = new Date(startOfToday.getTime() + 7 * 24 * 3600 * 1000);
  const startOfNextMonth = new Date(startOfToday.getFullYear(), startOfToday.getMonth() + 1, startOfToday.getDate());
  if (d < startOfTomorrow) return "today";
  if (d < startOfNextWeek) return "week";
  if (d < startOfNextMonth) return "month";
  return "later";
}

function formatDateShort(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch { return iso; }
}

function addDaysISO(iso: string | undefined | null, days: number): string {
  const base = iso && iso.length ? new Date(iso + "T00:00:00") : new Date();
  base.setDate(base.getDate() + days);
  const yyyy = base.getFullYear();
  const mm = String(base.getMonth() + 1).padStart(2, "0");
  const dd = String(base.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function TaskListWithGrouping({
  tasks,
  onOpenTask,
  onChanged,
  emptyText = "No tasks yet.",
  testIDPrefix = "task",
}: {
  tasks: TaskLike[];
  onOpenTask?: (id: string) => void;
  onChanged: () => void | Promise<void>;
  emptyText?: string;
  testIDPrefix?: string;
}) {
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [rescheduleDate, setRescheduleDate] = useState("");
  const [error, setError] = useState<string | null>(null);

  const now = useMemo(() => new Date(), []);

  const sections = useMemo(() => {
    const buckets: Record<Bucket, TaskLike[]> = {
      today: [], week: [], month: [], later: [], no_date: [], done: [],
    };
    for (const t of tasks) {
      buckets[bucketOf(t, now)].push(t);
    }
    const order: Bucket[] = ["today", "week", "month", "later", "no_date", "done"];
    const priorityRank = (p: string) => (p === "high" ? 0 : p === "medium" ? 1 : 2);
    const sortByDateThenPriority = (a: TaskLike, b: TaskLike) => {
      const d = (a.due_date || "9999").localeCompare(b.due_date || "9999");
      if (d !== 0) return d;
      return priorityRank(a.priority) - priorityRank(b.priority);
    };
    return order
      .map((b) => ({ key: b, title: BUCKET_LABEL[b], data: buckets[b].sort(sortByDateThenPriority) }))
      .filter((s) => s.data.length > 0);
  }, [tasks, now]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const nx = new Set(prev);
      if (nx.has(id)) nx.delete(id); else nx.add(id);
      return nx;
    });
  }, []);

  const enterSelect = useCallback((id: string) => {
    setSelectMode(true);
    setSelected(new Set([id]));
  }, []);

  const exitSelect = useCallback(() => {
    setSelectMode(false);
    setSelected(new Set());
  }, []);

  const bulk = useCallback(async (action: "complete" | "archive" | "delete" | "reschedule_tomorrow" | "reschedule_week" | "reschedule_custom", custom?: string) => {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const ids = Array.from(selected);
      await Promise.all(ids.map(async (id) => {
        if (action === "complete") {
          await api.updateTask(id, { status: "done" });
        } else if (action === "archive") {
          await api.updateTask(id, { status: "cancelled" });
        } else if (action === "delete") {
          await api.deleteTask(id);
        } else if (action === "reschedule_tomorrow") {
          await api.updateTask(id, { due_date: addDaysISO(new Date().toISOString().slice(0, 10), 1) });
        } else if (action === "reschedule_week") {
          await api.updateTask(id, { due_date: addDaysISO(new Date().toISOString().slice(0, 10), 7) });
        } else if (action === "reschedule_custom" && custom) {
          await api.updateTask(id, { due_date: custom });
        }
      }));
      exitSelect();
      await onChanged();
    } catch (e: any) {
      setError(e?.message || "Bulk action failed.");
    } finally {
      setBusy(false);
    }
  }, [selected, onChanged, exitSelect]);

  const renderRow = ({ item }: { item: TaskLike }) => {
    const isSelected = selected.has(item.id);
    const done = item.status === "done" || item.status === "cancelled";
    return (
      <Pressable
        onPress={() => {
          if (selectMode) return toggleSelect(item.id);
          onOpenTask?.(item.id);
        }}
        onLongPress={() => enterSelect(item.id)}
        style={[styles.row, isSelected && styles.rowSelected]}
        testID={`${testIDPrefix}-row-${item.id}`}
      >
        {selectMode ? (
          <Ionicons
            name={isSelected ? "checkbox" : "square-outline"}
            size={20}
            color={isSelected ? colors.brandPrimary : colors.onSurfaceTertiary}
          />
        ) : (
          <Ionicons
            name={done ? "checkmark-circle" : "ellipse-outline"}
            size={18}
            color={done ? colors.success : colors.onSurfaceTertiary}
          />
        )}
        <View style={{ flex: 1 }}>
          <Text
            style={[styles.rowTitle, done && { textDecorationLine: "line-through", color: colors.onSurfaceTertiary }]}
            numberOfLines={1}
          >
            {item.title}
          </Text>
          <Text style={styles.rowMeta}>
            {item.priority} · {item.status}
            {item.due_date ? ` · ${formatDateShort(item.due_date)}` : ""}
          </Text>
        </View>
        {!selectMode ? <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} /> : null}
      </Pressable>
    );
  };

  const renderHeader = ({ section }: any) => (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{section.title}</Text>
      <Text style={styles.sectionCount}>{section.data.length}</Text>
    </View>
  );

  if (tasks.length === 0) {
    return <Text style={styles.emptyLine}>{emptyText}</Text>;
  }

  return (
    <View style={{ flex: 1 }}>
      {selectMode ? (
        <View style={styles.actionBar} testID={`${testIDPrefix}-actionbar`}>
          <Pressable onPress={exitSelect} hitSlop={8} style={styles.actionCancel}>
            <Ionicons name="close" size={18} color={colors.onSurface} />
            <Text style={styles.actionCancelText}>{selected.size} selected</Text>
          </Pressable>
          <View style={styles.actionButtons}>
            <ActionBtn icon="calendar-outline" label="Reschedule" onPress={() => setRescheduleOpen(true)} testID={`${testIDPrefix}-action-reschedule`} />
            <ActionBtn icon="checkmark-done" label="Complete" onPress={() => bulk("complete")} testID={`${testIDPrefix}-action-complete`} />
            <ActionBtn icon="archive-outline" label="Archive" onPress={() => bulk("archive")} testID={`${testIDPrefix}-action-archive`} />
            <ActionBtn icon="trash-outline" label="Delete" onPress={() => bulk("delete")} danger testID={`${testIDPrefix}-action-delete`} />
          </View>
        </View>
      ) : null}

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
      {busy ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: spacing.sm }} /> : null}

      <SectionList
        sections={sections}
        keyExtractor={(item) => item.id}
        renderItem={renderRow}
        renderSectionHeader={renderHeader}
        stickySectionHeadersEnabled
        initialNumToRender={20}
        maxToRenderPerBatch={30}
        windowSize={7}
        scrollEnabled={false}
      />

      <RescheduleModal
        visible={rescheduleOpen}
        onCancel={() => setRescheduleOpen(false)}
        onPickPreset={(d) => { setRescheduleOpen(false); bulk("reschedule_custom", d); }}
        rescheduleDate={rescheduleDate}
        setRescheduleDate={setRescheduleDate}
        onConfirmCustom={() => {
          if (!rescheduleDate || !/^\d{4}-\d{2}-\d{2}$/.test(rescheduleDate)) {
            setError("Enter a valid date (YYYY-MM-DD)");
            return;
          }
          setRescheduleOpen(false);
          bulk("reschedule_custom", rescheduleDate);
        }}
      />
    </View>
  );
}

function ActionBtn({
  icon, label, onPress, danger, testID,
}: {
  icon: any; label: string; onPress: () => void; danger?: boolean; testID?: string;
}) {
  return (
    <Pressable onPress={onPress} style={styles.actionBtn} testID={testID}>
      <Ionicons name={icon} size={18} color={danger ? colors.error : colors.onSurface} />
      <Text style={[styles.actionLabel, danger && { color: colors.error }]}>{label}</Text>
    </Pressable>
  );
}

function RescheduleModal({
  visible, onCancel, onPickPreset, rescheduleDate, setRescheduleDate, onConfirmCustom,
}: {
  visible: boolean;
  onCancel: () => void;
  onPickPreset: (d: string) => void;
  rescheduleDate: string;
  setRescheduleDate: (v: string) => void;
  onConfirmCustom: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.modalBackdrop} onPress={onCancel}>
        <Pressable style={styles.modalCard} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.modalTitle}>Reschedule selected</Text>
          <Pressable style={styles.presetBtn} onPress={() => onPickPreset(addDaysISO(today, 1))} testID="reschedule-tomorrow">
            <Text style={styles.presetLabel}>Tomorrow</Text>
            <Text style={styles.presetDate}>{addDaysISO(today, 1)}</Text>
          </Pressable>
          <Pressable style={styles.presetBtn} onPress={() => onPickPreset(addDaysISO(today, 7))} testID="reschedule-week">
            <Text style={styles.presetLabel}>In 1 week</Text>
            <Text style={styles.presetDate}>{addDaysISO(today, 7)}</Text>
          </Pressable>
          <Pressable style={styles.presetBtn} onPress={() => onPickPreset(addDaysISO(today, 30))} testID="reschedule-month">
            <Text style={styles.presetLabel}>In 1 month</Text>
            <Text style={styles.presetDate}>{addDaysISO(today, 30)}</Text>
          </Pressable>
          <Text style={styles.orLabel}>Or pick a date (YYYY-MM-DD)</Text>
          <TextInput
            value={rescheduleDate}
            onChangeText={setRescheduleDate}
            placeholder="2026-07-15"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.dateInput}
            testID="reschedule-custom-input"
          />
          <View style={styles.modalRow}>
            <Pressable onPress={onCancel} style={styles.modalBtn} testID="reschedule-cancel">
              <Text style={styles.modalBtnText}>Cancel</Text>
            </Pressable>
            <Pressable onPress={onConfirmCustom} style={[styles.modalBtn, styles.modalBtnPrimary]} testID="reschedule-confirm">
              <Text style={[styles.modalBtnText, { color: colors.onBrandPrimary }]}>Reschedule</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sectionHeader: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    backgroundColor: colors.surface,
    paddingTop: spacing.md, paddingBottom: 6,
  },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.onSurface, fontWeight: "600", letterSpacing: 0.3, textTransform: "uppercase" },
  sectionCount: { fontSize: 11, color: colors.onSurfaceTertiary },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginBottom: spacing.xs,
  },
  rowSelected: { backgroundColor: colors.brandPrimary + "22", borderWidth: 1, borderColor: colors.brandPrimary },
  rowTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  emptyLine: { color: colors.onSurfaceTertiary, fontSize: 13, marginTop: spacing.xs },
  errorText: { color: colors.error, fontSize: 12, marginVertical: spacing.xs },
  actionBar: {
    backgroundColor: colors.surface, paddingVertical: spacing.sm, gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderStrong,
    marginBottom: spacing.sm,
  },
  actionCancel: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.md },
  actionCancelText: { fontSize: 13, color: colors.onSurface, fontWeight: "500" },
  actionButtons: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, paddingHorizontal: spacing.md },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.pill,
  },
  actionLabel: { fontSize: 12, color: colors.onSurface, fontWeight: "500" },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: spacing.xl },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.md },
  modalTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600" },
  presetBtn: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.md, borderRadius: radius.md,
  },
  presetLabel: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  presetDate: { fontSize: 12, color: colors.onSurfaceSecondary },
  orLabel: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1, textTransform: "uppercase", marginTop: spacing.sm },
  dateInput: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: 15,
  },
  modalRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  modalBtn: { flex: 1, backgroundColor: colors.surfaceSecondary, padding: spacing.md, borderRadius: radius.pill, alignItems: "center" },
  modalBtnPrimary: { backgroundColor: colors.brandPrimary },
  modalBtnText: { color: colors.onSurface, fontWeight: "600" },
});
