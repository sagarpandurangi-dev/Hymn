/**
 * Shared Portfolio panels reused by BOTH the setup wizard (/portfolio/setup)
 * and the You -> Portfolio editor (/portfolio). Every write goes through the
 * existing Portfolio APIs — nothing is buffered locally.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import {
  ACCOUNT_PRESET_BY_CODE,
  DAYS_OF_WEEK,
  DAY_LABELS,
  DayOfWeek,
  MONEY_COMMITMENT_PRESETS,
  TIME_CATEGORY_LABEL,
  formatMoney,
  localMondayISO,
  localMonthISO,
  splitCrossMidnight,
} from "@/src/lib/portfolio/constants";
import TimeBlockEditor, { TimeBlockDraft } from "./TimeBlockEditor";
import AccountEditor, { AccountDraft } from "./AccountEditor";
import MoneyCommitmentEditor, { MoneyCommitmentDraft } from "./MoneyCommitmentEditor";

// ============================================================================
// Weekly Time Portfolio
// ============================================================================

export function WeeklyTimePortfolio({ onChanged }: { onChanged?: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorDay, setEditorDay] = useState<DayOfWeek>("monday");
  const [editorInitial, setEditorInitial] = useState<TimeBlockDraft | undefined>(undefined);
  const [capacity, setCapacity] = useState<any | null>(null);
  // Copy-to modal — pick which target days receive a copy of the source day's blocks.
  const [copyOpen, setCopyOpen] = useState(false);
  const [copySource, setCopySource] = useState<DayOfWeek | null>(null);
  const [copyTargets, setCopyTargets] = useState<DayOfWeek[]>([]);
  const [copyBusy, setCopyBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [list, cap] = await Promise.all([
        api.listTimeCommitments(),
        api.getWeeklyTimeCapacity(localMondayISO()).catch(() => null as any),
      ]);
      setItems(list);
      setCapacity(cap);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    (async () => { setLoading(true); await reload(); setLoading(false); })();
  }, [reload]);

  const byDay: Record<DayOfWeek, any[]> = useMemo(() => {
    const acc: Record<DayOfWeek, any[]> = {
      monday: [], tuesday: [], wednesday: [], thursday: [], friday: [], saturday: [], sunday: [],
    };
    items.forEach((b) => {
      const key = b.day_of_week as DayOfWeek;
      if (acc[key]) acc[key].push(b);
    });
    (Object.keys(acc) as DayOfWeek[]).forEach((d) => acc[d].sort((a, b) => a.start_time.localeCompare(b.start_time)));
    return acc;
  }, [items]);

  const draftsByDay: Record<DayOfWeek, TimeBlockDraft[]> = useMemo(() => {
    const acc = {} as Record<DayOfWeek, TimeBlockDraft[]>;
    (DAYS_OF_WEEK as readonly DayOfWeek[]).forEach((d) => {
      acc[d] = byDay[d].map((b) => ({
        id: b.id, title: b.title, start_time: b.start_time, end_time: b.end_time,
        commitment_type: b.commitment_type, flexibility: b.flexibility,
      }));
    });
    return acc;
  }, [byDay]);

  const openAdd = (day: DayOfWeek) => {
    setEditorDay(day);
    setEditorInitial(undefined);
    setEditorOpen(true);
  };
  const openEdit = (day: DayOfWeek, block: TimeBlockDraft) => {
    setEditorDay(day);
    setEditorInitial(block);
    setEditorOpen(true);
  };

  const saveBlock = async (payload: {
    id?: string;
    title: string;
    commitment_type: string;
    flexibility: "fixed" | "flexible";
    entries: { day: DayOfWeek; start_time: string; end_time: string }[];
  }) => {
    // Recurring weekly commitments start "this week onward" — we backdate
    // `effective_from` to the current Monday so the running weekly capacity
    // math shows the new block regardless of which day the user logs it on.
    const effective_from = localMondayISO();

    if (payload.id) {
      // Editing: single record, single entry (editor locks day for edits).
      const first = payload.entries[0];
      await api.updateTimeCommitment(payload.id, {
        title: payload.title,
        day_of_week: first.day,
        start_time: first.start_time,
        end_time: first.end_time,
        commitment_type: payload.commitment_type,
        flexibility: payload.flexibility,
      });
    } else {
      // Creating: one entry per record. Cross-midnight blocks emit 2
      // entries per selected day (day D 22:30 → 24:00 AND day D+1 00:00
      // → 06:30). Multi-day selection emits N entries per day.
      await Promise.all(
        payload.entries.map((p) =>
          api.createTimeCommitment({
            title: payload.title,
            day_of_week: p.day,
            start_time: p.start_time,
            end_time: p.end_time,
            commitment_type: payload.commitment_type,
            flexibility: payload.flexibility,
            effective_from,
            effective_until: null,
            source_type: "onboarding",
            source_id: null,
          }),
        ),
      );
    }
    await reload();
    onChanged?.();
  };

  const deleteBlock = (id: string) => {
    Alert.alert("Delete block", "Remove this weekly time block?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try { await api.deleteTimeCommitment(id); await reload(); onChanged?.(); } catch { /* ignore */ }
        },
      },
    ]);
  };

  const openCopy = (source: DayOfWeek) => {
    setCopySource(source);
    setCopyTargets([]);
    setCopyOpen(true);
  };

  const runCopy = async () => {
    if (!copySource || copyTargets.length === 0) return;
    setCopyBusy(true);
    try {
      const sourceBlocks = byDay[copySource];
      const effective_from = localMondayISO();
      // Clone each source block into each target day. Cross-midnight splits
      // already sit as two independent records on the source, so a straight
      // copy preserves that shape without re-splitting.
      const jobs: Promise<any>[] = [];
      for (const target of copyTargets) {
        for (const b of sourceBlocks) {
          jobs.push(api.createTimeCommitment({
            title: b.title,
            day_of_week: target,
            start_time: b.start_time,
            end_time: b.end_time,
            commitment_type: b.commitment_type,
            flexibility: b.flexibility,
            effective_from,
            effective_until: null,
            source_type: "onboarding",
            source_id: null,
          }));
        }
      }
      await Promise.all(jobs);
      // Silence unused warning for splitCrossMidnight — kept for future use.
      void splitCrossMidnight;
      await reload();
      onChanged?.();
      setCopyOpen(false);
      setCopySource(null);
      setCopyTargets([]);
    } catch (e: any) {
      Alert.alert("Copy failed", e?.message || "Please try again.");
    } finally {
      setCopyBusy(false);
    }
  };

  const capacityByDay: Record<string, { committed_minutes: number; available_minutes: number }> = useMemo(() => {
    const m: Record<string, { committed_minutes: number; available_minutes: number }> = {};
    if (capacity?.days) {
      capacity.days.forEach((d: any) => {
        m[d.day_of_week] = { committed_minutes: d.committed_minutes, available_minutes: d.available_minutes };
      });
    }
    return m;
  }, [capacity]);

  const totalCommitted = capacity?.days ? capacity.days.reduce((a: number, d: any) => a + d.committed_minutes, 0) : 0;
  const totalAvailable = capacity?.days ? capacity.days.reduce((a: number, d: any) => a + d.available_minutes, 0) : 0;
  const fmtHrs = (min: number) => `${(min / 60).toFixed(1)} h`;

  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.lg }} />;

  return (
    <View style={{ gap: spacing.md }}>
      <View style={styles.weekTotals}>
        <View style={styles.weekTotalCell}>
          <Text style={styles.weekTotalLabel}>Weekly committed</Text>
          <Text style={styles.weekTotalValue} testID="week-total-committed">{fmtHrs(totalCommitted)}</Text>
        </View>
        <View style={styles.weekTotalCell}>
          <Text style={styles.weekTotalLabel}>Weekly available</Text>
          <Text style={styles.weekTotalValue} testID="week-total-available">{fmtHrs(totalAvailable)}</Text>
        </View>
      </View>

      {DAYS_OF_WEEK.map((day) => {
        const blocks = byDay[day];
        const cap = capacityByDay[day];
        const dayId = day;
        const hasBlocks = blocks.length > 0;
        return (
          <View key={day} style={styles.dayCard} testID={`day-card-${dayId}`}>
            <View style={styles.dayHeader}>
              <Text style={styles.dayName}>{DAY_LABELS[day]}</Text>
              <View style={styles.dayHeaderRight}>
                {cap && (
                  <Text style={styles.dayCapacity} testID={`day-capacity-${dayId}`}>
                    {fmtHrs(cap.committed_minutes)} / {fmtHrs(cap.available_minutes)} free
                  </Text>
                )}
                {hasBlocks && (
                  <Pressable
                    onPress={() => openCopy(day)}
                    hitSlop={12}
                    testID={`day-copy-${dayId}`}
                    style={styles.copyBtn}
                  >
                    <Ionicons name="copy-outline" size={14} color={colors.onSurfaceSecondary} />
                    <Text style={styles.copyBtnText}>Copy to…</Text>
                  </Pressable>
                )}
                <Pressable
                  onPress={() => openAdd(day)}
                  hitSlop={12}
                  testID={`day-add-${dayId}`}
                  style={styles.addBtn}
                >
                  <Ionicons name="add" size={16} color={colors.onBrandPrimary} />
                </Pressable>
              </View>
            </View>
            {!hasBlocks ? (
              <Text style={styles.empty}>No blocks yet.</Text>
            ) : (
              <View style={{ gap: spacing.xs }}>
                {blocks.map((b) => (
                  <Pressable
                    key={b.id}
                    onPress={() =>
                      openEdit(day, {
                        id: b.id,
                        title: b.title,
                        start_time: b.start_time,
                        end_time: b.end_time,
                        commitment_type: b.commitment_type,
                        flexibility: b.flexibility,
                      })
                    }
                    onLongPress={() => deleteBlock(b.id)}
                    style={styles.block}
                    testID={`block-${b.id}`}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.blockTitle} numberOfLines={1}>{b.title}</Text>
                      <Text style={styles.blockMeta}>
                        {b.start_time}–{b.end_time} · {TIME_CATEGORY_LABEL[b.commitment_type] || b.commitment_type} · {b.flexibility}
                      </Text>
                    </View>
                    <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
                  </Pressable>
                ))}
              </View>
            )}
          </View>
        );
      })}

      <TimeBlockEditor
        visible={editorOpen}
        day={editorDay}
        initial={editorInitial}
        existingByDay={draftsByDay}
        onSubmit={saveBlock}
        onClose={() => setEditorOpen(false)}
      />

      <Modal visible={copyOpen} animationType="slide" transparent onRequestClose={() => setCopyOpen(false)}>
        <View style={styles.copyModalWrap}>
          <View style={styles.copyModalCard}>
            <View style={styles.copyModalHead}>
              <Text style={styles.copyModalTitle}>
                Copy {copySource ? DAY_LABELS[copySource] : ""} to…
              </Text>
              <Pressable onPress={() => setCopyOpen(false)} hitSlop={12} testID="copy-close">
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <Text style={styles.copyModalBody}>
              Clones every block on {copySource ? DAY_LABELS[copySource] : "the source day"} onto the days you pick.
            </Text>
            <View style={styles.wrapRow}>
              {DAYS_OF_WEEK.filter((d) => d !== copySource).map((d) => {
                const sel = copyTargets.includes(d);
                return (
                  <Pressable
                    key={d}
                    onPress={() =>
                      setCopyTargets((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]))
                    }
                    style={[styles.chip, sel && styles.chipSel]}
                    testID={`copy-day-${d}`}
                  >
                    <Text style={[styles.chipText, sel && styles.chipTextSel]}>{DAY_LABELS[d].slice(0, 3)}</Text>
                  </Pressable>
                );
              })}
            </View>
            <Pressable
              onPress={runCopy}
              disabled={copyBusy || copyTargets.length === 0}
              style={[styles.copyCta, (copyBusy || copyTargets.length === 0) && { opacity: 0.5 }]}
              testID="copy-submit"
            >
              <Text style={styles.copyCtaText}>
                {copyBusy ? "Copying…" : `Copy to ${copyTargets.length || "0"} day${copyTargets.length === 1 ? "" : "s"}`}
              </Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ============================================================================
// Financial Position
// ============================================================================

export function FinancialPositionPanel({ defaultCurrency, onChanged }: { defaultCurrency: string; onChanged?: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorInitial, setEditorInitial] = useState<AccountDraft | undefined>(undefined);

  const reload = useCallback(async () => {
    try { setItems(await api.listFinancialAccounts()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { (async () => { setLoading(true); await reload(); setLoading(false); })(); }, [reload]);

  const save = async (draft: AccountDraft) => {
    const preset = ACCOUNT_PRESET_BY_CODE[draft.account_type];
    const payload = {
      account_type: draft.account_type,
      name: draft.name,
      currency: draft.currency,
      current_value: draft.current_value,
      liquidity_type: preset.liquidity_type,
      fixed_or_flexible: preset.fixed_or_flexible,
    };
    if (draft.id) await api.updateFinancialAccount(draft.id, payload);
    else await api.createFinancialAccount(payload);
    await reload();
    onChanged?.();
  };

  const remove = (id: string) => {
    Alert.alert("Delete account", "Remove this financial account?", [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try { await api.deleteFinancialAccount(id); await reload(); onChanged?.(); } catch { /* ignore */ }
      }},
    ]);
  };

  const grouped = useMemo(() => {
    const m: Record<string, any[]> = {};
    items.forEach((a) => { (m[a.currency] ||= []).push(a); });
    Object.keys(m).forEach((k) => m[k].sort((x, y) => x.name.localeCompare(y.name)));
    return m;
  }, [items]);

  const multiCurrency = Object.keys(grouped).length > 1;

  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.lg }} />;

  const isAsset = (t: string) => ACCOUNT_PRESET_BY_CODE[t]?.kind === "asset";
  const sumAssets = (rows: any[]) => rows.filter((a) => isAsset(a.account_type)).reduce((s, a) => s + Number(a.current_value || 0), 0);
  const sumLiab = (rows: any[]) => rows.filter((a) => !isAsset(a.account_type)).reduce((s, a) => s + Number(a.current_value || 0), 0);

  return (
    <View style={{ gap: spacing.md }}>
      <Pressable
        style={styles.primaryBtn}
        onPress={() => { setEditorInitial(undefined); setEditorOpen(true); }}
        testID="account-add"
      >
        <Ionicons name="add" size={16} color={colors.onBrandPrimary} />
        <Text style={styles.primaryBtnText}>Add account</Text>
      </Pressable>

      {items.length === 0 ? (
        <Text style={styles.empty}>Add at least one asset or liability.</Text>
      ) : null}

      {multiCurrency && (
        <Text style={styles.notice} testID="fx-notice">Cross-currency totals are not combined until currency conversion is enabled.</Text>
      )}

      {Object.keys(grouped).sort().map((cur) => {
        const rows = grouped[cur];
        const assets = sumAssets(rows);
        const liab = sumLiab(rows);
        const net = assets - liab;
        return (
          <View key={cur} style={styles.curCard} testID={`accounts-currency-${cur}`}>
            <Text style={styles.curTitle}>{cur}</Text>
            <View style={styles.curTotals}>
              <View style={styles.curTotalCell}><Text style={styles.curTotalLabel}>Assets</Text><Text style={styles.curTotalValue}>{formatMoney(assets)}</Text></View>
              <View style={styles.curTotalCell}><Text style={styles.curTotalLabel}>Liabilities</Text><Text style={styles.curTotalValue}>{formatMoney(liab)}</Text></View>
              <View style={styles.curTotalCell}><Text style={styles.curTotalLabel}>Net</Text><Text style={styles.curTotalValue}>{formatMoney(net)}</Text></View>
            </View>
            <View style={{ gap: spacing.xs }}>
              {rows.map((a) => (
                <Pressable
                  key={a.id}
                  onPress={() => { setEditorInitial({ id: a.id, account_type: a.account_type, name: a.name, currency: a.currency, current_value: a.current_value }); setEditorOpen(true); }}
                  onLongPress={() => remove(a.id)}
                  style={styles.acctRow}
                  testID={`account-${a.id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.acctName}>{a.name}</Text>
                    <Text style={styles.acctMeta}>
                      {ACCOUNT_PRESET_BY_CODE[a.account_type]?.label || a.account_type}
                      {isAsset(a.account_type) ? " · Asset" : " · Liability"}
                    </Text>
                  </View>
                  <Text style={styles.acctValue}>{formatMoney(a.current_value)}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        );
      })}

      <AccountEditor
        visible={editorOpen}
        initial={editorInitial}
        defaultCurrency={defaultCurrency}
        onSubmit={save}
        onClose={() => setEditorOpen(false)}
      />
    </View>
  );
}

// ============================================================================
// Monthly Money Commitments
// ============================================================================

export function MonthlyMoneyPanel({ defaultCurrency, onChanged }: { defaultCurrency: string; onChanged?: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorInitial, setEditorInitial] = useState<MoneyCommitmentDraft | undefined>(undefined);
  const [positions, setPositions] = useState<Record<string, any>>({});

  const reload = useCallback(async () => {
    try {
      const list = await api.listMonthlyMoneyCommitments();
      setItems(list);
      const curs = Array.from(new Set(list.map((x: any) => x.currency)));
      const month = localMonthISO();
      const positionsMap: Record<string, any> = {};
      await Promise.all(
        curs.map(async (c) => {
          try { positionsMap[c] = await api.getMonthlyMoneyPosition(month, c); } catch { /* ignore */ }
        }),
      );
      setPositions(positionsMap);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { (async () => { setLoading(true); await reload(); setLoading(false); })(); }, [reload]);

  const save = async (draft: MoneyCommitmentDraft) => {
    const payload = {
      title: draft.title,
      currency: draft.currency,
      amount: draft.amount,
      commitment_type: draft.commitment_type,
      fixed_or_flexible: draft.fixed_or_flexible,
      start_month: draft.start_month,
      end_month: draft.end_month,
      source_type: "onboarding",
      source_id: null,
    };
    if (draft.id) await api.updateMonthlyMoneyCommitment(draft.id, payload);
    else await api.createMonthlyMoneyCommitment(payload);
    await reload();
    onChanged?.();
  };

  const remove = (id: string) => {
    Alert.alert("Delete commitment", "Remove this monthly commitment?", [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try { await api.deleteMonthlyMoneyCommitment(id); await reload(); onChanged?.(); } catch { /* ignore */ }
      }},
    ]);
  };

  const grouped = useMemo(() => {
    const m: Record<string, any[]> = {};
    items.forEach((c) => { (m[c.currency] ||= []).push(c); });
    Object.keys(m).forEach((k) => m[k].sort((x, y) => x.start_month.localeCompare(y.start_month)));
    return m;
  }, [items]);

  const multiCurrency = Object.keys(grouped).length > 1;

  if (loading) return <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.lg }} />;

  const groupLabel = (t: string) => {
    const p = MONEY_COMMITMENT_PRESETS.find((x) => x.commitment_type === t);
    return p?.group || t;
  };

  return (
    <View style={{ gap: spacing.md }}>
      <Pressable
        style={styles.primaryBtn}
        onPress={() => { setEditorInitial(undefined); setEditorOpen(true); }}
        testID="money-add"
      >
        <Ionicons name="add" size={16} color={colors.onBrandPrimary} />
        <Text style={styles.primaryBtnText}>Add commitment</Text>
      </Pressable>

      {items.length === 0 && <Text style={styles.empty}>Add at least one monthly commitment.</Text>}

      {multiCurrency && (
        <Text style={styles.notice} testID="fx-notice-money">Cross-currency totals are not combined until currency conversion is enabled.</Text>
      )}

      {Object.keys(grouped).sort().map((cur) => {
        const rows = grouped[cur];
        const pos = positions[cur];
        return (
          <View key={cur} style={styles.curCard} testID={`money-currency-${cur}`}>
            <Text style={styles.curTitle}>{cur}</Text>
            {pos && (
              <View style={styles.posGrid}>
                <View style={styles.posCell}><Text style={styles.posLabel}>Planned income</Text><Text style={styles.posValue}>{formatMoney(pos.planned_income)}</Text></View>
                <View style={styles.posCell}><Text style={styles.posLabel}>Fixed outflows</Text><Text style={styles.posValue}>{formatMoney(pos.fixed_outflows)}</Text></View>
                <View style={styles.posCell}><Text style={styles.posLabel}>Planned savings</Text><Text style={styles.posValue}>{formatMoney(pos.planned_savings)}</Text></View>
                <View style={styles.posCell}><Text style={styles.posLabel}>Planned investments</Text><Text style={styles.posValue}>{formatMoney(pos.planned_investments)}</Text></View>
                <View style={styles.posCell}><Text style={styles.posLabel}>Actual spending</Text><Text style={styles.posValue}>{formatMoney(pos.actual_spending)}</Text></View>
                <View style={[styles.posCell, { flexBasis: "100%" }]}><Text style={styles.posLabel}>Available for flexible spending</Text><Text style={styles.posValueStrong}>{formatMoney(pos.available_for_flexible_spending)}</Text></View>
              </View>
            )}
            <View style={{ gap: spacing.xs, marginTop: spacing.sm }}>
              {rows.map((c) => (
                <Pressable
                  key={c.id}
                  onPress={() => { setEditorInitial({
                    id: c.id, title: c.title, amount: c.amount, currency: c.currency,
                    start_month: c.start_month, end_month: c.end_month || "",
                    commitment_type: c.commitment_type, fixed_or_flexible: "fixed",
                  }); setEditorOpen(true); }}
                  onLongPress={() => remove(c.id)}
                  style={styles.acctRow}
                  testID={`money-${c.id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.acctName}>{c.title}</Text>
                    <Text style={styles.acctMeta}>{groupLabel(c.commitment_type)} · from {c.start_month}{c.end_month ? ` → ${c.end_month}` : ""}</Text>
                  </View>
                  <Text style={styles.acctValue}>{formatMoney(c.amount)}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        );
      })}

      <MoneyCommitmentEditor
        visible={editorOpen}
        initial={editorInitial}
        defaultCurrency={defaultCurrency}
        onSubmit={save}
        onClose={() => setEditorOpen(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  weekTotals: {
    flexDirection: "row",
    gap: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.lg,
    borderRadius: radius.md,
  },
  weekTotalCell: { flex: 1 },
  weekTotalLabel: { fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  weekTotalValue: { fontSize: 20, color: colors.onSurface, fontWeight: "700", marginTop: 2 },
  dayCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  dayHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dayName: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  dayHeaderRight: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  dayCapacity: { fontSize: 12, color: colors.onSurfaceSecondary },
  addBtn: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center",
  },
  empty: { fontSize: 13, color: colors.onSurfaceSecondary, fontStyle: "italic" },
  block: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  blockTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  blockMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.brandPrimary,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  primaryBtnText: { color: colors.onBrandPrimary, fontSize: 14, fontWeight: "600" },
  notice: {
    fontSize: 12,
    color: colors.onSurfaceSecondary,
    backgroundColor: colors.brandTertiary,
    padding: spacing.md,
    borderRadius: radius.sm,
  },
  curCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  curTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "700", letterSpacing: 0.5 },
  curTotals: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xs },
  curTotalCell: { flex: 1 },
  curTotalLabel: { fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  curTotalValue: { fontSize: 16, color: colors.onSurface, fontWeight: "600", marginTop: 2 },
  acctRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
  },
  acctName: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  acctMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  acctValue: { fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  posGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.xs },
  posCell: { flexBasis: "48%" },
  posLabel: { fontSize: 11, color: colors.onSurfaceSecondary },
  posValue: { fontSize: 14, color: colors.onSurface, fontWeight: "600", marginTop: 2 },
  posValueStrong: { fontSize: 16, color: colors.brandPrimary, fontWeight: "700", marginTop: 2 },
});
