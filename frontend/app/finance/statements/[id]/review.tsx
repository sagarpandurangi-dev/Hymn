import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";
import {
  api, ApiError, StatementConfirmResult, StatementDecision, StatementSuggestion,
  StatementSuggestionLine, StatementSuggestions,
} from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

type Account = { id: string; name: string; currency: string };
type Choice = StatementSuggestion & { always?: boolean; changed?: boolean };

const KINDS: { value: string; label: string }[] = [
  { value: "expense", label: "Expense" },
  { value: "income", label: "Income" },
  { value: "card_bill", label: "Card bill" },
  { value: "transfer", label: "Transfer" },
  { value: "refund", label: "Refund" },
  { value: "skip", label: "Skip" },
];
const EXPENSE_CATEGORIES = [
  "food", "groceries", "fuel", "transport", "shopping", "bills", "rent", "health", "education",
  "entertainment", "travel", "family", "personal_care", "insurance", "taxes", "charity",
  "subscriptions", "uncategorised",
];
const INCOME_CATEGORIES = ["salary", "bonus", "interest", "gift", "refund", "other", "uncategorised"];

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const categoryName = (c?: string | null) => (c ? c.split(":").pop() || "" : "");

function suggestionLabel(s?: Choice | null): string {
  if (!s) return "No suggestion";
  if (s.duplicate_of || s.action === "link" || s.action === "linked" || s.action === "already_recorded") return "Already recorded";
  const kind = KINDS.find((k) => k.value === s.kind)?.label ?? (s.kind ? titleCase(s.kind) : "");
  const cat = categoryName(s.category);
  return [kind, cat ? titleCase(cat) : ""].filter(Boolean).join(" · ") || (s.action ? titleCase(s.action) : "No suggestion");
}

function confidenceColor(c?: string | null) {
  if (c === "matched" || c === "rule") return financeColors.positive;
  if (c === "learned") return financeColors.pillInfoInk;
  return financeColors.inkMuted;
}

const lineAmount = (l: StatementSuggestionLine) => {
  const has = (v: unknown) => v !== null && v !== undefined && v !== "" && Number(v) !== 0;
  if (has(l.debit)) return { text: `−${formatMoney(String(l.debit))}`, out: true };
  if (has(l.credit)) return { text: `+${formatMoney(String(l.credit))}`, out: false };
  return { text: "", out: false };
};

function Chip({ label, selected, onPress, testID }: { label: string; selected: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, selected && styles.chipSel]} testID={testID}>
      <Text style={[styles.chipText, selected && styles.chipTextSel]}>{label}</Text>
    </Pressable>
  );
}

export default function StatementReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const importId = String(id);
  const [data, setData] = useState<StatementSuggestions | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [linking, setLinking] = useState<string | null>(null);
  const [editing, setEditing] = useState<StatementSuggestionLine | null>(null);
  const [draft, setDraft] = useState<Choice | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<StatementConfirmResult | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [sug, accs] = await Promise.all([
        api.getStatementSuggestions(importId),
        api.listFinancialAccounts().catch(() => []),
      ]);
      setData(sug);
      setAccounts((accs as Account[]) || []);
      const init: Record<number, Choice> = {};
      for (const l of sug.lines ?? []) init[l.n] = { ...(l.suggestion ?? {}) };
      setChoices(init);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, [importId]);

  useEffect(() => {
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, [load]);

  const link = async (accountId: string) => {
    if (linking) return;
    setLinking(accountId);
    setError("");
    try {
      await api.linkStatementAccount(importId, accountId);
      await load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setLinking(null);
    }
  };

  const openEdit = (l: StatementSuggestionLine) => {
    setEditing(l);
    setDraft({ ...(choices[l.n] ?? {}) });
  };

  const saveEdit = () => {
    if (!editing || !draft) return;
    setChoices((prev) => ({ ...prev, [editing.n]: { ...draft, changed: true } }));
    setEditing(null);
    setDraft(null);
  };

  const pickKind = (kind: string) => {
    setDraft((d) => ({
      ...(d ?? {}),
      kind,
      action: kind === "skip" ? "skip" : "create",
      category: kind === "expense" ? "expense:uncategorised" : kind === "income" ? "income:uncategorised" : null,
      counter_account_id: kind === "card_bill" || kind === "transfer" ? d?.counter_account_id ?? null : null,
      duplicate_of: null,
      merge_with: null,
      confidence: null,
      why: null,
    }));
  };

  const confirmAll = async () => {
    const lines = data?.lines ?? [];
    if (confirming || lines.length === 0) return;
    setConfirming(true);
    setError("");
    try {
      const decisions: StatementDecision[] = lines.map((l) => {
        const c = choices[l.n] ?? {};
        const d: StatementDecision = {
          n: l.n,
          action: c.action ?? null,
          kind: c.kind ?? null,
          category: c.category ?? null,
          counter_account_id: c.counter_account_id ?? null,
          duplicate_of: c.duplicate_of ?? null,
          merge_with: c.merge_with ?? null,
        };
        if (c.always) d.always = true;
        return d;
      });
      setResult(await api.confirmStatement(importId, decisions));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setConfirming(false);
    }
  };

  const accountName = (aid?: string | null) => accounts.find((a) => a.id === aid)?.name ?? "";
  const suggested = data?.account_suggestions ?? [];
  const orderedAccounts = [
    ...suggested.map((sid) => accounts.find((a) => a.id === sid)).filter((a): a is Account => !!a),
    ...accounts.filter((a) => !suggested.includes(a.id)),
  ];

  const renderResult = (r: StatementConfirmResult) => {
    const bc = r.balance_check;
    return (
      <FoldCard style={styles.resultCard} testID="statement-confirm-result">
        <Text style={styles.resultText}>
          {`${r.created ?? 0} added, ${r.linked_to_existing ?? 0} already recorded, ${r.merged ?? 0} fixed, ${r.skipped ?? 0} skipped`}
        </Text>
        {bc?.available ? (
          bc.matches ? (
            <Text style={[styles.resultText, { color: financeColors.positive }]}>✓ Matches the statement&apos;s closing balance</Text>
          ) : (
            <Text style={[styles.resultText, { color: financeColors.negative }]}>
              {`Money book: ${formatMoney(String(bc.ledger_balance ?? ""))} · Statement: ${formatMoney(String(bc.statement_closing ?? ""))}`}
            </Text>
          )
        ) : null}
      </FoldCard>
    );
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Review & confirm" subtitle="Check each line, then confirm" />
      {loading ? <ActivityIndicator style={{ marginTop: financeSpace.xxxl }} color={financeColors.ink} /> : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {error ? <Text style={styles.error} testID="statement-review-error">{error}</Text> : null}

          {data && !data.account_id ? (
            <>
              <Text style={styles.question}>Which account is this statement for?</Text>
              <FoldCard>
                {orderedAccounts.length === 0 ? <Text style={styles.empty}>No accounts yet.</Text> : null}
                {orderedAccounts.map((a, i) => (
                  <FoldRow
                    key={a.id}
                    first={i === 0}
                    label={a.name}
                    meta={a.currency}
                    right={linking === a.id ? <ActivityIndicator color={financeColors.ink} /> : a.id === suggested[0] ? <Text style={styles.suggested}>Suggested</Text> : undefined}
                    onPress={() => link(a.id)}
                    chevron
                    testID={`statement-link-account-${a.id}`}
                  />
                ))}
              </FoldCard>
            </>
          ) : data ? (
            <>
              {result ? renderResult(result) : null}
              <FoldCard>
                {(data.lines ?? []).length === 0 ? <Text style={styles.empty}>No lines to review.</Text> : null}
                {(data.lines ?? []).map((l, i) => {
                  const c = choices[l.n];
                  const amt = lineAmount(l);
                  return (
                    <Pressable
                      key={l.n}
                      onPress={() => !result && openEdit(l)}
                      style={[styles.line, i > 0 && styles.lineBorder]}
                      testID={`statement-review-line-${l.n}`}
                    >
                      <View style={styles.lineHead}>
                        <Text style={styles.lineDate}>{l.date || ""}</Text>
                        <Text style={styles.lineDesc} numberOfLines={2}>{l.description || ""}</Text>
                        <Text style={[styles.lineAmt, amt.out ? styles.out : styles.in]}>{amt.text}</Text>
                      </View>
                      <Text style={[styles.sugLabel, { color: confidenceColor(c?.confidence) }]}>
                        {suggestionLabel(c)}
                        {c?.counter_account_id && accountName(c.counter_account_id) ? ` → ${accountName(c.counter_account_id)}` : ""}
                        {c?.always ? " · Always" : ""}
                      </Text>
                      {c?.why ? <Text style={styles.why}>{c.why}</Text> : null}
                    </Pressable>
                  );
                })}
              </FoldCard>
              {!result && (data.lines ?? []).length > 0 ? (
                <Pressable style={[styles.primary, confirming && styles.disabled]} onPress={confirmAll} disabled={confirming} testID="statement-confirm-all-button">
                  {confirming ? <ActivityIndicator color="#FBFBF6" /> : <Text style={styles.primaryText}>Confirm all</Text>}
                </Pressable>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      )}

      <Modal visible={!!editing} transparent animationType="slide" onRequestClose={() => setEditing(null)}>
        <View style={styles.backdrop}>
          <View style={styles.sheet}>
            <ScrollView contentContainerStyle={{ gap: financeSpace.md }}>
              <Text style={styles.sheetTitle} numberOfLines={2}>{editing?.description}</Text>
              <Text style={styles.fieldLabel}>Kind</Text>
              <View style={styles.chipWrap}>
                {KINDS.map((k) => (
                  <Chip key={k.value} label={k.label} selected={draft?.kind === k.value} onPress={() => pickKind(k.value)} testID={`statement-kind-${k.value}`} />
                ))}
              </View>

              {draft?.kind === "expense" || draft?.kind === "income" ? (
                <>
                  <Text style={styles.fieldLabel}>Category</Text>
                  <View style={styles.chipWrap}>
                    {(draft.kind === "expense" ? EXPENSE_CATEGORIES : INCOME_CATEGORIES).map((cat) => {
                      const value = `${draft.kind}:${cat}`;
                      return (
                        <Chip
                          key={cat}
                          label={titleCase(cat)}
                          selected={draft.category === value}
                          onPress={() => setDraft((d) => ({ ...(d ?? {}), category: value }))}
                          testID={`statement-category-${cat}`}
                        />
                      );
                    })}
                  </View>
                </>
              ) : null}

              {draft?.kind === "card_bill" || draft?.kind === "transfer" ? (
                <>
                  <Text style={styles.fieldLabel}>Other account</Text>
                  <View style={styles.chipWrap}>
                    {accounts.filter((a) => a.id !== data?.account_id).map((a) => (
                      <Chip
                        key={a.id}
                        label={a.name}
                        selected={draft.counter_account_id === a.id}
                        onPress={() => setDraft((d) => ({ ...(d ?? {}), counter_account_id: a.id }))}
                        testID={`statement-counter-${a.id}`}
                      />
                    ))}
                  </View>
                </>
              ) : null}

              <View style={styles.switchRow}>
                <Text style={styles.switchLabel}>Always do this</Text>
                <Switch
                  value={!!draft?.always}
                  onValueChange={(v) => setDraft((d) => ({ ...(d ?? {}), always: v }))}
                  trackColor={{ false: financeColors.divider, true: financeColors.ink }}
                  testID="statement-always-switch"
                />
              </View>

              <View style={styles.sheetActions}>
                <Pressable style={styles.secondary} onPress={() => { setEditing(null); setDraft(null); }} testID="statement-edit-cancel">
                  <Text style={styles.secondaryText}>Cancel</Text>
                </Pressable>
                <Pressable style={[styles.primary, styles.flex1]} onPress={saveEdit} testID="statement-edit-save">
                  <Text style={styles.primaryText}>Done</Text>
                </Pressable>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: financeSpace.xl, gap: financeSpace.md, paddingBottom: financeSpace.xxxl },
  error: { fontSize: 13, color: financeColors.negative },
  empty: { fontSize: 13, color: financeColors.inkMuted, padding: financeSpace.xl, textAlign: "center", fontStyle: "italic" },
  question: { fontSize: 16, fontWeight: "700", color: financeColors.ink },
  suggested: { fontSize: 11, fontWeight: "700", color: financeColors.positive },
  line: { paddingVertical: financeSpace.md, paddingHorizontal: financeSpace.lg, gap: 3 },
  lineBorder: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider },
  lineHead: { flexDirection: "row", alignItems: "flex-start", gap: financeSpace.md },
  lineDate: { width: 78, fontSize: 12, color: financeColors.inkMuted },
  lineDesc: { flex: 1, fontSize: 13.5, color: financeColors.ink },
  lineAmt: { fontSize: 13.5, fontWeight: "700", fontVariant: ["tabular-nums"] },
  out: { color: financeColors.ink },
  in: { color: financeColors.positive },
  sugLabel: { fontSize: 13, fontWeight: "700", marginLeft: 78 + financeSpace.md },
  why: { fontSize: 11.5, color: financeColors.inkMuted, marginLeft: 78 + financeSpace.md },
  resultCard: { padding: financeSpace.lg, gap: financeSpace.xs },
  resultText: { fontSize: 14, color: financeColors.ink, fontWeight: "600" },
  primary: { backgroundColor: financeColors.ink, minHeight: 48, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center", paddingHorizontal: financeSpace.lg },
  primaryText: { color: "#FBFBF6", fontSize: 14, fontWeight: "700" },
  secondary: { minHeight: 48, paddingHorizontal: financeSpace.lg, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", justifyContent: "center" },
  secondaryText: { color: financeColors.ink, fontSize: 14, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  flex1: { flex: 1 },
  backdrop: { flex: 1, backgroundColor: "rgba(20,20,18,0.4)", justifyContent: "flex-end" },
  sheet: { backgroundColor: financeColors.card, borderTopLeftRadius: financeRadius.lg, borderTopRightRadius: financeRadius.lg, padding: financeSpace.xl, maxHeight: "85%" },
  sheetTitle: { fontSize: 16, fontWeight: "700", color: financeColors.ink },
  fieldLabel: { fontSize: 12, fontWeight: "600", color: financeColors.inkMuted, letterSpacing: 0.4 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm },
  chip: { minHeight: 36, paddingHorizontal: financeSpace.md, borderRadius: financeRadius.pill, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, alignItems: "center", justifyContent: "center" },
  chipSel: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipText: { fontSize: 13, color: financeColors.ink },
  chipTextSel: { color: "#FBFBF6", fontWeight: "700" },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  switchLabel: { fontSize: 15, color: financeColors.ink },
  sheetActions: { flexDirection: "row", gap: financeSpace.md, marginTop: financeSpace.sm },
});
