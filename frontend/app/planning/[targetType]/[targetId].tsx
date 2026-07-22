import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, spacing, radius, fonts } from "@/src/lib/theme";

type Proposal = {
  id: string;
  target_type: "goal" | "project" | "journey";
  target_id: string;
  status: string;
  version: number;
  snapshot_hash: string;
  objective_summary?: string;
  measurable_success_criteria?: string;
  current_state: Array<{
    field: string;
    value: any;
    evidence: string;
    confidence: string;
    source?: string;
    note?: string;
  }>;
  confirmation_items: any[];
  blocking_questions: Array<{ field: string; question: string; why_blocking?: string }>;
  proposed_outcomes: any[];
  proposed_tasks: any[];
  proposed_check_ins: any[];
  visual_phases: Array<{ label: string; tasks: string[] }>;
  resource_requirements: any[];
  portfolio_conflicts: any[];
  assumptions: string[];
  external_estimates: any[];
  risks: string[];
  feasibility: { status: string; reasons: string[]; tradeoffs: string[]; alternatives: any[] };
  approval_actions: any[];
  evidence_map: any[];
  validation_errors: string[];
  created_at: string;
  approved_at?: string;
  rejected_at?: string;
};

const confidenceStyle: Record<string, any> = {
  high: { backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary },
  medium: { backgroundColor: "#F5E6C7", color: "#7A5C1C" },
  low: { backgroundColor: "#F4D1CB", color: "#7A2B1E" },
};

const statusLabels: Record<string, string> = {
  confirmation_required: "Awaiting confirmation",
  blocking_input_required: "Needs your input",
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
  const router = useRouter();

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runAnalyze = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const p = await api.planningAnalyze({ target_type: targetType, target_id: targetId });
      setProposal(p);
    } catch (e: any) {
      setError(e.message || "Failed to analyze");
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId]);

  useEffect(() => {
    // Try to load the latest existing proposal first; if none, analyze fresh.
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

  const confirmField = async (field: string, action: "confirm" | "reject" | "mark_unknown") => {
    if (!proposal) return;
    try {
      setBusy(`confirm-${field}`);
      const p = await api.planningConfirm(proposal.id, [{ field, action }]);
      setProposal(p);
    } catch (e: any) {
      Alert.alert("Confirm failed", e.message || "Please try again");
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!proposal) return;
    Alert.alert(
      "Approve proposal?",
      "This will create the proposed outcomes, tasks, and reservations in your portfolio. It cannot be undone from here.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Approve",
          style: "default",
          onPress: async () => {
            try {
              setBusy("approve");
              const res = await api.planningApprove(proposal.id);
              Alert.alert("Approved", `Committed ${res.committed_actions} action(s).`);
              // Reload latest proposal to reflect new status.
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
  const canApprove =
    !isTerminal &&
    proposal.validation_errors.length === 0 &&
    ["feasible", "feasible_with_tradeoffs"].includes(proposal.feasibility.status);

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
            <FeasibilityPill status={proposal.feasibility.status} />
          </View>
          <Text style={styles.subtitle}>
            {proposal.measurable_success_criteria || "Success criteria: unknown"}
          </Text>
          <Pressable onPress={runAnalyze} style={styles.reanalyzeBtn} disabled={busy === "analyze"}>
            <Ionicons name="refresh" size={16} color={colors.onSurfaceSecondary} />
            <Text style={styles.reanalyzeText}>Re-analyze from live portfolio</Text>
          </Pressable>
        </View>

        {/* Current state */}
        <Section title="Current state (from your portfolio)">
          {proposal.current_state.map((f, i) => (
            <View key={i} style={styles.factRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.factField}>{prettyField(f.field)}</Text>
                <Text style={styles.factValue}>{prettyValue(f.value)}</Text>
                {f.note ? <Text style={styles.factNote}>{f.note}</Text> : null}
                <View style={styles.row}>
                  <ConfidencePill confidence={f.confidence} />
                  <Text style={styles.evidenceText}>via {f.evidence}</Text>
                </View>
              </View>
              {!isTerminal && (
                <View style={styles.factActions}>
                  <Pressable onPress={() => confirmField(f.field, "confirm")} disabled={!!busy}>
                    <Ionicons name="checkmark-circle" size={22} color={colors.success} />
                  </Pressable>
                  <Pressable onPress={() => confirmField(f.field, "mark_unknown")} disabled={!!busy}>
                    <Ionicons name="help-circle" size={22} color={colors.warning} />
                  </Pressable>
                  <Pressable onPress={() => confirmField(f.field, "reject")} disabled={!!busy}>
                    <Ionicons name="close-circle" size={22} color={colors.error} />
                  </Pressable>
                </View>
              )}
            </View>
          ))}
        </Section>

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
                {o.target_date && o.target_date !== "unknown" ? (
                  <Text style={styles.itemDetail}>Target: {o.target_date}</Text>
                ) : null}
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
                  {t.target_date && t.target_date !== "unknown" ? (
                    <Text style={styles.itemMeta}>Due {t.target_date}</Text>
                  ) : null}
                  {t.required_resources?.time_minutes ? (
                    <Text style={styles.itemMeta}>{t.required_resources.time_minutes} min</Text>
                  ) : null}
                  {t.required_resources?.money?.amount ? (
                    <Text style={styles.itemMeta}>
                      {t.required_resources.money.currency || ""} {t.required_resources.money.amount}
                    </Text>
                  ) : null}
                </View>
                <ConfidencePill confidence={t.confidence || "low"} />
              </View>
            ))}
          </Section>
        )}

        {/* Visual phases */}
        {proposal.visual_phases.length > 0 && (
          <Section title="Visual phases (display only)">
            {proposal.visual_phases.map((p, i) => (
              <View key={i} style={styles.phaseCard}>
                <Text style={styles.phaseLabel}>{p.label}</Text>
                <Text style={styles.itemDetail}>{p.tasks.length} task{p.tasks.length === 1 ? "" : "s"}</Text>
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
                <Text style={styles.itemDetail}>{JSON.stringify(c.detail ?? c)}</Text>
              </View>
            ))}
          </Section>
        )}

        {/* Feasibility reasons */}
        {(proposal.feasibility.reasons.length > 0 || proposal.feasibility.alternatives.length > 0) && (
          <Section title="Feasibility">
            {proposal.feasibility.reasons.map((r, i) => (
              <Text key={i} style={styles.reasonText}>• {prettyField(r)}</Text>
            ))}
            {proposal.feasibility.alternatives.map((a: any, i: number) => (
              <View key={i} style={styles.altCard}>
                <Text style={styles.itemMeta}>{prettyField(a.conflict?.kind || "alternative")}</Text>
                {(a.options || []).map((o: any, j: number) => (
                  <Text key={j} style={styles.itemDetail}>→ {o.action}: {o.rationale}</Text>
                ))}
              </View>
            ))}
          </Section>
        )}

        {/* Assumptions / risks */}
        {proposal.assumptions.length > 0 && (
          <Section title="Assumptions">
            {proposal.assumptions.map((a, i) => (
              <Text key={i} style={styles.reasonText}>• {a}</Text>
            ))}
          </Section>
        )}
        {proposal.risks.length > 0 && (
          <Section title="Risks">
            {proposal.risks.map((r, i) => (
              <Text key={i} style={styles.reasonText}>• {r}</Text>
            ))}
          </Section>
        )}

        {/* Validation errors */}
        {proposal.validation_errors.length > 0 && (
          <Section title="Validation errors">
            {proposal.validation_errors.map((e, i) => (
              <Text key={i} style={[styles.reasonText, { color: colors.error }]}>• {e}</Text>
            ))}
          </Section>
        )}

        {/* Actions to approve */}
        {!isTerminal && (
          <Section title={`Actions if you approve (${proposal.approval_actions.length})`}>
            {proposal.approval_actions.slice(0, 12).map((a, i) => (
              <Text key={i} style={styles.itemDetail}>• {prettyField(a.action)}: {a.payload?.title || ""}</Text>
            ))}
          </Section>
        )}

        {/* Approve / reject */}
        {!isTerminal && (
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
                : "Approval is blocked while the plan has validation errors, unknown feasibility, or open blocking questions."}
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

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
  const c = confidenceStyle[confidence] || confidenceStyle.low;
  return (
    <View style={[styles.pillSmall, { backgroundColor: c.backgroundColor }]}>
      <Text style={[styles.pillTextSmall, { color: c.color }]}>{confidence}</Text>
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
  return f.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
  blockerCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  blockerField: { fontFamily: fonts.body, fontSize: 12, color: colors.brandSecondary, textTransform: "uppercase" },
  blockerQuestion: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onSurface, marginTop: 2 },
  blockerWhy: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  itemCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  itemTitle: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onSurface },
  itemDetail: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  itemMeta: { fontFamily: fonts.body, fontSize: 11, color: colors.onSurfaceTertiary },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.xs },
  phaseCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  phaseLabel: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.onSurface },
  conflictCard: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  conflictKind: { fontFamily: fonts.displayBold, fontSize: 13, color: colors.error },
  reasonText: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  altCard: { paddingVertical: spacing.sm },
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
