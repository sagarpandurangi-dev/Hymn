import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, spacing, radius, fonts } from "@/src/lib/theme";

type FactAction = "confirm" | "edit" | "reject" | "mark_unknown";

type Fact = {
  evidence_id: string;
  field: string;
  value: any;
  evidence: string;
  confidence: string;
  source?: string;
  note?: string;
  blocking?: boolean;
};

type Proposal = {
  id: string;
  target_type: "goal" | "project" | "journey";
  target_id: string;
  status: string;
  version: number;
  snapshot_hash: string;
  objective_summary?: string;
  measurable_success_criteria?: string | null;
  current_state: Fact[];
  confirmations: Record<string, { action: FactAction; value?: any; note?: string; recorded_at?: string }>;
  ready_to_generate?: boolean;
  blocking_questions: Array<{ field: string; question: string; why_blocking?: string }>;
  proposed_outcomes: any[];
  proposed_tasks: any[];
  proposed_check_ins: any[];
  visual_phases: Array<{ label: string; tasks: string[] }>;
  resource_requirements: any[];
  portfolio_conflicts: any[];
  assumptions: any[];
  external_estimates: any[];
  risks: any[];
  feasibility: {
    status: string;
    reasons: string[];
    tradeoffs?: any[];
    alternatives?: any[];
    selected_tradeoff_id?: string | null;
  };
  approval_actions: any[];
  validation_errors: string[];
  selected_tradeoff_id?: string | null;
  commit_phase?: string | null;
  approved_at?: string;
  rejected_at?: string;
};

const statusLabels: Record<string, string> = {
  confirmation_required: "Confirm current state",
  blocking_input_required: "Needs your input",
  generating: "Generating proposal…",
  proposal_ready: "Ready to approve",
  infeasible: "Not currently feasible",
  approved: "Approved",
  rejected: "Rejected",
  abandoned: "Abandoned",
  paused: "Paused",
  error: "Error",
};

export default function PlanningScreen() {
  const params = useLocalSearchParams<{ targetType?: string; targetId?: string }>();
  const targetType = params.targetType as "goal" | "project" | "journey";
  const targetId = params.targetId!;

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Batched decisions the user made in-session for the current view.
  const [pending, setPending] = useState<
    Record<string, { action: FactAction; value?: any }>
  >({});

  const runAnalyze = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setPending({});
      const p = await api.planningAnalyze({ target_type: targetType, target_id: targetId });
      setProposal(p);
    } catch (e: any) {
      setError(e.message || "Failed to analyze");
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const list = await api.planningListProposals(targetType, targetId);
        if (!cancelled) {
          if (list && list.length > 0) {
            setProposal(list[0] as Proposal);
            setLoading(false);
          } else {
            await runAnalyze();
          }
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message || "Failed to load");
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [runAnalyze, targetType, targetId]);

  const setDecision = (field: string, action: FactAction, value?: any) => {
    setPending((prev) => ({ ...prev, [field]: { action, value } }));
  };

  const submitAllConfirmations = async () => {
    if (!proposal) return;
    const entries = Object.entries(pending).map(([field, v]) => ({
      field,
      action: v.action,
      value: v.value,
    }));
    if (entries.length === 0) {
      Alert.alert("Nothing to submit", "Confirm, edit, mark-unknown or reject at least one field.");
      return;
    }
    try {
      setBusy("confirm");
      const p = await api.planningConfirm(proposal.id, entries);
      setProposal(p);
      setPending({});
    } catch (e: any) {
      Alert.alert("Confirm failed", e.message || "Please try again");
    } finally {
      setBusy(null);
    }
  };

  const generate = async () => {
    if (!proposal) return;
    try {
      setBusy("generate");
      const p = await api.planningGenerate(proposal.id);
      setProposal(p);
    } catch (e: any) {
      Alert.alert("Generate failed", e.message || "Please try again");
    } finally {
      setBusy(null);
    }
  };

  const selectTradeoff = async (id: string) => {
    if (!proposal) return;
    try {
      setBusy("tradeoff");
      const p = await api.planningSelectTradeoff(proposal.id, id);
      setProposal(p);
    } catch (e: any) {
      Alert.alert("Trade-off selection failed", e.message || "Please try again");
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!proposal) return;
    Alert.alert(
      "Approve proposal?",
      "This will create the proposed outcomes, tasks, and reservations in your portfolio.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Approve",
          onPress: async () => {
            try {
              setBusy("approve");
              const res = await api.planningApprove(proposal.id);
              Alert.alert("Approved", `Committed ${res.committed_actions} action(s).`);
              const p = await api.planningGetProposal(proposal.id);
              setProposal(p);
            } catch (e: any) {
              if (e.status === 409) {
                Alert.alert("Portfolio changed", "Re-analyzing…");
                await runAnalyze();
              } else {
                Alert.alert("Approve failed", e.message || "Please try again");
              }
            } finally {
              setBusy(null);
            }
          },
        },
      ],
    );
  };

  const reject = async () => {
    if (!proposal) return;
    Alert.alert("Reject proposal?", "All future planning allocations will be released.", [
      { text: "Keep", style: "cancel" },
      {
        text: "Reject",
        style: "destructive",
        onPress: async () => {
          try {
            setBusy("reject");
            await api.planningReject(proposal.id);
            const p = await api.planningGetProposal(proposal.id);
            setProposal(p);
          } catch (e: any) {
            Alert.alert("Reject failed", e.message || "Please try again");
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  };

  const feasibility = proposal?.feasibility?.status ?? "unknown";
  const needsTradeoff = feasibility === "feasible_with_tradeoffs";
  const canApprove = useMemo(() => {
    if (!proposal) return false;
    if (proposal.status !== "proposal_ready") return false;
    if (proposal.validation_errors.length > 0) return false;
    if (feasibility === "not_currently_feasible" || feasibility === "unknown") return false;
    if (needsTradeoff && !proposal.selected_tradeoff_id) return false;
    return true;
  }, [proposal, feasibility, needsTradeoff]);

  const stillBlocking = useMemo(() => (proposal?.current_state || []).some((f) => f.blocking), [proposal]);
  const canGenerate = useMemo(() => {
    if (!proposal) return false;
    if (["approved", "rejected", "abandoned"].includes(proposal.status)) return false;
    return !stillBlocking && (proposal.proposed_tasks?.length ?? 0) === 0;
  }, [proposal, stillBlocking]);

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <Stack.Screen options={{ title: "Planning" }} />
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={styles.loadingText}>Reading your portfolio…</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (error && !proposal) {
    return (
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        <Stack.Screen options={{ title: "Planning" }} />
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.primaryBtn} onPress={runAnalyze}>
            <Text style={styles.primaryBtnText}>Retry</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (!proposal) return null;

  const isTerminal = ["approved", "rejected", "abandoned"].includes(proposal.status);
  const showConfirmForm = proposal.status === "confirmation_required" && (proposal.proposed_tasks?.length ?? 0) === 0;

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Planning" }} />
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Header */}
        <View style={styles.card}>
          <Text style={styles.eyebrow}>Version {proposal.version}</Text>
          <Text style={styles.title}>{proposal.objective_summary || "Objective"}</Text>
          <View style={styles.row}>
            <StatusPill status={proposal.status} />
            <FeasibilityPill status={feasibility} />
          </View>
          {proposal.measurable_success_criteria ? (
            <Text style={styles.subtitle}>{proposal.measurable_success_criteria}</Text>
          ) : null}
          <Pressable onPress={runAnalyze} style={styles.reanalyzeBtn} disabled={!!busy}>
            <Ionicons name="refresh" size={16} color={colors.onSurfaceSecondary} />
            <Text style={styles.reanalyzeText}>Re-analyze from live portfolio</Text>
          </Pressable>
        </View>

        {/* Confirmation form */}
        {showConfirmForm && (
          <Section title="Confirm current state">
            {proposal.current_state.map((f) => (
              <ConfirmRow
                key={f.evidence_id}
                fact={f}
                pending={pending[f.field]}
                onDecision={setDecision}
              />
            ))}
            <View style={styles.actionsCard}>
              <Pressable
                onPress={submitAllConfirmations}
                disabled={!!busy}
                style={[styles.primaryBtn, !!busy && styles.btnDisabled]}
              >
                {busy === "confirm" ? (
                  <ActivityIndicator color={colors.onBrandPrimary} />
                ) : (
                  <Text style={styles.primaryBtnText}>Submit confirmations</Text>
                )}
              </Pressable>
              <Text style={styles.helperText}>
                All your decisions are submitted together in one request. No LLM call is made here.
              </Text>
            </View>
          </Section>
        )}

        {/* Generate button */}
        {!isTerminal && canGenerate && (
          <View style={[styles.card, { marginTop: spacing.md }]}>
            <Text style={styles.sectionTitle}>Ready to generate</Text>
            <Text style={styles.helperText}>
              All required fields are resolved. Generating will make one LLM call using only your confirmed context.
            </Text>
            <Pressable
              onPress={generate}
              disabled={!!busy}
              style={[styles.primaryBtn, { marginTop: spacing.sm }, !!busy && styles.btnDisabled]}
            >
              {busy === "generate" ? (
                <ActivityIndicator color={colors.onBrandPrimary} />
              ) : (
                <Text style={styles.primaryBtnText}>Generate proposal</Text>
              )}
            </Pressable>
          </View>
        )}

        {/* Current state readout (post-confirm view) */}
        {!showConfirmForm && (
          <Section title="Current state">
            {proposal.current_state.map((f) => (
              <View key={f.evidence_id} style={styles.factRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.factField}>{prettyField(f.field)}</Text>
                  <Text style={styles.factValue}>{prettyValue(f.value)}</Text>
                  {f.note ? <Text style={styles.factNote}>{f.note}</Text> : null}
                  <View style={styles.row}>
                    <ConfidencePill confidence={f.confidence} />
                    <Text style={styles.evidenceText}>via {f.evidence}</Text>
                    {f.blocking ? (
                      <Text style={[styles.evidenceText, { color: colors.error }]}>· blocking</Text>
                    ) : null}
                  </View>
                </View>
              </View>
            ))}
          </Section>
        )}

        {/* Blocking questions */}
        {proposal.blocking_questions.length > 0 && (
          <Section title="Blocking questions">
            {proposal.blocking_questions.map((q, i) => (
              <View key={i} style={styles.blockerCard}>
                <Text style={styles.blockerField}>{prettyField(q.field)}</Text>
                <Text style={styles.blockerQuestion}>{q.question}</Text>
                {q.why_blocking ? (
                  <Text style={styles.blockerWhy}>Why blocking: {q.why_blocking}</Text>
                ) : null}
              </View>
            ))}
          </Section>
        )}

        {/* Proposed outcomes */}
        {proposal.proposed_outcomes.length > 0 && (
          <Section title={`Proposed expected outcomes (${proposal.proposed_outcomes.length})`}>
            {proposal.proposed_outcomes.map((o, i) => (
              <View key={i} style={styles.itemCard}>
                <Text style={styles.itemTitle}>{o.title}</Text>
                {o.measurable_end_state ? (
                  <Text style={styles.itemDetail}>End state: {o.measurable_end_state}</Text>
                ) : null}
                {o.target_date ? <Text style={styles.itemDetail}>Target: {o.target_date}</Text> : null}
              </View>
            ))}
          </Section>
        )}

        {/* Proposed tasks */}
        {proposal.proposed_tasks.length > 0 && (
          <Section title={`Proposed tasks (${proposal.proposed_tasks.length})`}>
            {proposal.proposed_tasks.map((t, i) => (
              <View key={i} style={styles.itemCard}>
                <Text style={styles.itemTitle}>{t.title}</Text>
                {t.completion_condition ? (
                  <Text style={styles.itemDetail}>Done when: {t.completion_condition}</Text>
                ) : null}
                <View style={styles.metaRow}>
                  {t.target_date ? <Text style={styles.itemMeta}>Due {t.target_date}</Text> : null}
                  {t.required_resources?.time_minutes ? (
                    <Text style={styles.itemMeta}>{t.required_resources.time_minutes} min</Text>
                  ) : null}
                  {t.required_resources?.money?.amount ? (
                    <Text style={styles.itemMeta}>
                      {t.required_resources.money.currency} {t.required_resources.money.amount}
                    </Text>
                  ) : null}
                  {t.reuse_existing_task_id ? (
                    <Text style={[styles.itemMeta, { color: colors.brandSecondary }]}>reuse</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </Section>
        )}

        {/* Portfolio conflicts */}
        {proposal.portfolio_conflicts.length > 0 && (
          <Section title="Portfolio conflicts">
            {proposal.portfolio_conflicts.map((c, i) => (
              <View key={i} style={styles.conflictCard}>
                <Text style={styles.conflictKind}>{prettyField(c.kind)}</Text>
                <Text style={styles.itemDetail}>{JSON.stringify(c)}</Text>
              </View>
            ))}
          </Section>
        )}

        {/* Assumptions */}
        {proposal.assumptions.length > 0 && (
          <Section title="Assumptions (require your confirmation)">
            {proposal.assumptions.map((a, i) => (
              <View key={i} style={styles.itemCard}>
                <Text style={styles.itemTitle}>{a.statement}</Text>
                {a.range ? <Text style={styles.itemDetail}>Range: {a.range}</Text> : null}
              </View>
            ))}
          </Section>
        )}

        {/* Feasibility + trade-offs */}
        {feasibility !== "unknown" && (
          <Section title="Feasibility">
            {proposal.feasibility.reasons.map((r, i) => (
              <Text key={i} style={styles.reasonText}>• {prettyField(r)}</Text>
            ))}
            {needsTradeoff && (
              <View style={{ marginTop: spacing.sm }}>
                <Text style={styles.helperText}>
                  Select a trade-off before you can approve.
                </Text>
                {(proposal.feasibility.alternatives || []).map((alt: any, i: number) => (
                  <View key={i}>
                    <Text style={styles.itemMeta}>{prettyField(alt.kind || "alternative")}</Text>
                    {(alt.options || []).map((opt: any) => {
                      const selected = proposal.selected_tradeoff_id === opt.id;
                      return (
                        <Pressable
                          key={opt.id}
                          onPress={() => selectTradeoff(opt.id)}
                          disabled={!!busy}
                          style={[styles.tradeoffBtn, selected && styles.tradeoffBtnSelected]}
                        >
                          <Ionicons
                            name={selected ? "radio-button-on" : "radio-button-off"}
                            size={18}
                            color={selected ? colors.brandPrimary : colors.onSurfaceSecondary}
                          />
                          <View style={{ flex: 1 }}>
                            <Text style={styles.tradeoffTitle}>{prettyField(opt.action)}</Text>
                            <Text style={styles.itemDetail}>{opt.rationale}</Text>
                          </View>
                        </Pressable>
                      );
                    })}
                  </View>
                ))}
              </View>
            )}
          </Section>
        )}

        {/* Risks */}
        {proposal.risks.length > 0 && (
          <Section title="Risks">
            {proposal.risks.map((r, i) => (
              <Text key={i} style={styles.reasonText}>• {r.description}</Text>
            ))}
          </Section>
        )}

        {/* Validation errors */}
        {proposal.validation_errors.length > 0 && (
          <Section title="Validation errors (approval blocked)">
            {proposal.validation_errors.map((e, i) => (
              <Text key={i} style={[styles.reasonText, { color: colors.error }]}>• {e}</Text>
            ))}
          </Section>
        )}

        {/* Approve / reject */}
        {!isTerminal && (proposal.proposed_tasks?.length ?? 0) > 0 && (
          <View style={styles.actionsCard}>
            <Pressable
              onPress={approve}
              disabled={!canApprove || !!busy}
              style={[styles.primaryBtn, (!canApprove || !!busy) && styles.btnDisabled]}
            >
              {busy === "approve" ? (
                <ActivityIndicator color={colors.onBrandPrimary} />
              ) : (
                <Text style={styles.primaryBtnText}>Approve & commit</Text>
              )}
            </Pressable>
            <Pressable onPress={reject} disabled={!!busy} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnText}>Reject proposal</Text>
            </Pressable>
            <Text style={styles.helperText}>
              {canApprove
                ? "Nothing is written until you approve."
                : needsTradeoff && !proposal.selected_tradeoff_id
                  ? "Select a trade-off above before approving."
                  : "Approval blocked while the plan has validation errors, unknown feasibility, or unresolved blockers."}
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ==========================================================================
// Row for a single fact — supports confirm / edit / mark_unknown / reject.
// ==========================================================================

function ConfirmRow({
  fact,
  pending,
  onDecision,
}: {
  fact: Fact;
  pending?: { action: FactAction; value?: any };
  onDecision: (field: string, action: FactAction, value?: any) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState<string>(
    typeof fact.value === "string" ? fact.value : "",
  );
  const active = pending?.action;
  return (
    <View style={styles.factRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.factField}>{prettyField(fact.field)}</Text>
        {editing ? (
          <TextInput
            value={editValue}
            onChangeText={setEditValue}
            onBlur={() => {
              onDecision(fact.field, "edit", editValue);
              setEditing(false);
            }}
            style={styles.editInput}
            placeholder="Enter value"
            placeholderTextColor={colors.onSurfaceTertiary}
            autoFocus
          />
        ) : (
          <Text style={styles.factValue}>{prettyValue(pending?.value ?? fact.value)}</Text>
        )}
        {fact.note ? <Text style={styles.factNote}>{fact.note}</Text> : null}
        <View style={styles.row}>
          <ConfidencePill confidence={fact.confidence} />
          <Text style={styles.evidenceText}>via {fact.evidence}</Text>
          {fact.blocking ? (
            <Text style={[styles.evidenceText, { color: colors.error }]}>· blocking</Text>
          ) : null}
        </View>
        {active ? (
          <Text style={[styles.evidenceText, { color: colors.brandSecondary, marginTop: 4 }]}>
            Pending: {active}
          </Text>
        ) : null}
      </View>
      <View style={styles.factActions}>
        <Pressable
          onPress={() => onDecision(fact.field, "confirm")}
          hitSlop={8}
        >
          <Ionicons
            name="checkmark-circle"
            size={22}
            color={active === "confirm" ? colors.success : colors.onSurfaceTertiary}
          />
        </Pressable>
        <Pressable onPress={() => setEditing(true)} hitSlop={8}>
          <Ionicons
            name="create-outline"
            size={22}
            color={active === "edit" ? colors.brandPrimary : colors.onSurfaceTertiary}
          />
        </Pressable>
        <Pressable onPress={() => onDecision(fact.field, "mark_unknown")} hitSlop={8}>
          <Ionicons
            name="help-circle"
            size={22}
            color={active === "mark_unknown" ? colors.warning : colors.onSurfaceTertiary}
          />
        </Pressable>
        <Pressable onPress={() => onDecision(fact.field, "reject")} hitSlop={8}>
          <Ionicons
            name="close-circle"
            size={22}
            color={active === "reject" ? colors.error : colors.onSurfaceTertiary}
          />
        </Pressable>
      </View>
    </View>
  );
}

// ==========================================================================
// Small components
// ==========================================================================

function StatusPill({ status }: { status: string }) {
  return (
    <View style={[styles.pill, { backgroundColor: colors.surfaceTertiary }]}>
      <Text style={[styles.pillText, { color: colors.onSurface }]}>{statusLabels[status] || status}</Text>
    </View>
  );
}

function FeasibilityPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    feasible: { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
    feasible_with_tradeoffs: { bg: "#F5E6C7", fg: "#7A5C1C" },
    not_currently_feasible: { bg: "#F4D1CB", fg: "#7A2B1E" },
    unknown: { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary },
  };
  const c = map[status] || map.unknown;
  return (
    <View style={[styles.pill, { backgroundColor: c.bg }]}>
      <Text style={[styles.pillText, { color: c.fg }]}>Feasibility: {prettyField(status)}</Text>
    </View>
  );
}

function ConfidencePill({ confidence }: { confidence: string }) {
  const cmap: Record<string, { bg: string; fg: string }> = {
    high: { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
    medium: { bg: "#F5E6C7", fg: "#7A5C1C" },
    low: { bg: "#F4D1CB", fg: "#7A2B1E" },
  };
  const c = cmap[confidence] || cmap.low;
  return (
    <View style={[styles.pillSmall, { backgroundColor: c.bg }]}>
      <Text style={[styles.pillTextSmall, { color: c.fg }]}>{confidence}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

function prettyField(f: string) {
  return String(f).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function prettyValue(v: any): string {
  if (v === null || v === undefined) return "unknown";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxxl },
  loadingText: { marginTop: spacing.md, color: colors.onSurfaceSecondary, fontFamily: fonts.body },
  errorText: { color: colors.error, marginBottom: spacing.md, fontFamily: fonts.body },
  eyebrow: { color: colors.onSurfaceSecondary, fontSize: 12, letterSpacing: 1, textTransform: "uppercase", marginBottom: spacing.xs, fontFamily: fonts.body },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginBottom: spacing.sm },
  subtitle: { fontFamily: fonts.body, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, marginBottom: spacing.md, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, alignItems: "center", marginTop: spacing.sm },
  section: { marginTop: spacing.md },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: colors.onSurface, marginBottom: spacing.sm, marginLeft: spacing.xs },
  pill: { paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.body, fontSize: 12 },
  pillSmall: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, alignSelf: "flex-start", marginTop: spacing.xs },
  pillTextSmall: { fontFamily: fonts.body, fontSize: 10, fontWeight: "600" },
  factRow: { flexDirection: "row", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, paddingVertical: spacing.sm, alignItems: "flex-start" },
  factField: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.onSurface },
  factValue: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  factNote: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 2, fontStyle: "italic" },
  factActions: { flexDirection: "row", gap: spacing.sm, paddingLeft: spacing.sm },
  evidenceText: { fontFamily: fonts.body, fontSize: 11, color: colors.onSurfaceTertiary },
  editInput: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurface, borderBottomWidth: 1, borderBottomColor: colors.borderStrong, paddingVertical: 4, marginTop: 4 },
  blockerCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  blockerField: { fontFamily: fonts.body, fontSize: 12, color: colors.brandSecondary, textTransform: "uppercase" },
  blockerQuestion: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onSurface, marginTop: 2 },
  blockerWhy: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  itemCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  itemTitle: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onSurface },
  itemDetail: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  itemMeta: { fontFamily: fonts.body, fontSize: 11, color: colors.onSurfaceTertiary },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.xs },
  conflictCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  conflictKind: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.error },
  reasonText: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  tradeoffBtn: { flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.sm, borderRadius: radius.md, alignItems: "flex-start" },
  tradeoffBtnSelected: { backgroundColor: colors.surfaceTertiary },
  tradeoffTitle: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.onSurface },
  actionsCard: { marginTop: spacing.lg, gap: spacing.sm },
  primaryBtn: { backgroundColor: colors.brandPrimary, paddingVertical: spacing.md, borderRadius: radius.md, alignItems: "center" },
  primaryBtnText: { color: colors.onBrandPrimary, fontFamily: fonts.displayBold, fontSize: 15 },
  secondaryBtn: { backgroundColor: colors.surfaceSecondary, paddingVertical: spacing.md, borderRadius: radius.md, alignItems: "center", borderWidth: 1, borderColor: colors.borderStrong },
  secondaryBtnText: { color: colors.onSurface, fontFamily: fonts.body, fontSize: 14 },
  btnDisabled: { opacity: 0.5 },
  helperText: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceTertiary, textAlign: "center", marginTop: spacing.xs },
  reanalyzeBtn: { flexDirection: "row", alignItems: "center", gap: spacing.xs, marginTop: spacing.md, paddingVertical: spacing.xs },
  reanalyzeText: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary },
});
