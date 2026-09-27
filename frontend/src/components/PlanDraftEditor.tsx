/**
 * Batch 2B9 — Editable Plan Review UI.
 *
 * Renders the durable Plan → Phase → Milestone → Task → Required Check-in
 * hierarchy for a single assistant proposal and delegates every mutation to
 * the backend hierarchy-operations endpoint. The component never mutates the
 * plan optimistically; it always replaces its local state with the response
 * the backend just committed.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  api,
  createPlanningOperationId,
  type PlanningHierarchyEntityType,
  type PlanningHierarchyOperationRequest,
  type PlanningMilestoneDraft,
  type PlanningPhaseDraft,
  type PlanningPlanDraft,
  type PlanningRequiredCheckinDraft,
  type PlanningTaskDraft,
} from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";
import DateTimeField from "@/src/components/DateTimeField";

/* -------------------------------------------------------------------- */
/*  Props                                                                */
/* -------------------------------------------------------------------- */

type Props = {
  conversationId: string;
  messageId: string;
  initialPlan: PlanningPlanDraft;
  initialRevision?: number | null;
  materializedAt?: string | null;
  materializedSummary?: string | null;
  materializationState?: string | null;
  onConversationUpdated: (conversation: unknown) => void;
};

type PendingOperation = {
  request: PlanningHierarchyOperationRequest;
  error: string;
};

type EditFormState = {
  entity_type: Exclude<PlanningHierarchyEntityType, "plan"> | "plan";
  entity_id: string;
  title: string;
  description: string;
  target_date: string;
  due_date: string;
  priority: "low" | "medium" | "high";
  prompt: string;
  cadence: PlanningRequiredCheckinDraft["cadence"];
  original: {
    title: string;
    description: string;
    target_date: string;
    due_date: string;
    priority: "low" | "medium" | "high";
    prompt: string;
    cadence: PlanningRequiredCheckinDraft["cadence"];
  };
};

type AddFormKind = "phase" | "milestone" | "task" | "required_checkin";
type AddFormState = {
  kind: AddFormKind;
  parent_id: string;
  parent_child_count: number;
  // Fields (all optional so a single state can carry all four forms).
  title: string;
  description: string;
  target_date: string;
  due_date: string;
  priority: "low" | "medium" | "high";
  first_milestone_title: string;
  first_task_title: string;
  first_checkin_title: string;
  prompt: string;
  cadence: PlanningRequiredCheckinDraft["cadence"];
};

type MoveTargetOption = { id: string; label: string };
type MoveState = {
  entity_type: "milestone" | "task" | "required_checkin";
  entity_id: string;
  current_parent_id: string;
  options: MoveTargetOption[];
};

type RemoveState = {
  entity_type: PlanningHierarchyEntityType;
  entity_id: string;
  title: string;
  will_cascade: boolean;
};

/* -------------------------------------------------------------------- */
/*  Constants                                                            */
/* -------------------------------------------------------------------- */

const PRIORITY_CHOICES: { value: "low" | "medium" | "high"; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

const CADENCE_CHOICES: { value: PlanningRequiredCheckinDraft["cadence"]; label: string }[] = [
  { value: "once", label: "Once" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
];

/* -------------------------------------------------------------------- */
/*  Component                                                            */
/* -------------------------------------------------------------------- */

export default function PlanDraftEditor({
  conversationId,
  messageId,
  initialPlan,
  initialRevision,
  materializedAt,
  materializedSummary,
  materializationState,
  onConversationUpdated,
}: Props) {
  const alreadyApplied = !!materializedAt || materializationState === "applied";
  const currentlyApplying = materializationState === "applying";
  const readOnly = alreadyApplied || currentlyApplying;

  const [plan, setPlan] = useState<PlanningPlanDraft>(initialPlan);
  const [revision, setRevision] = useState<number>(
    typeof initialRevision === "number" ? initialRevision : 1,
  );
  const [loaded, setLoaded] = useState<boolean>(readOnly);
  const [loading, setLoading] = useState<boolean>(!readOnly);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);
  const [pending, setPending] = useState<PendingOperation | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [collapsedPhaseIds, setCollapsedPhaseIds] = useState<Record<string, boolean>>({});
  const [editForm, setEditForm] = useState<EditFormState | null>(null);
  const [addForm, setAddForm] = useState<AddFormState | null>(null);
  const [moveState, setMoveState] = useState<MoveState | null>(null);
  const [removeState, setRemoveState] = useState<RemoveState | null>(null);
  const [applying, setApplying] = useState<boolean>(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [appliedSummary, setAppliedSummary] = useState<string | null>(
    alreadyApplied ? materializedSummary || "Plan added to Hymn." : null,
  );

  /* ---- load canonical hierarchy on mount --------------------------- */
  const reloadHierarchy = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await api.planningGetDraftHierarchy(conversationId, messageId);
      setPlan(res.plan);
      setRevision(res.proposal_revision);
      setLoaded(true);
      setPending(null);
    } catch (e: any) {
      setLoadError(e?.message || "Could not load this plan.");
    } finally {
      setLoading(false);
    }
  }, [conversationId, messageId]);

  useEffect(() => {
    if (readOnly) {
      setLoaded(true);
      setLoading(false);
      return;
    }
    void reloadHierarchy();
  }, [readOnly, reloadHierarchy]);

  /* ---- operation dispatcher ---------------------------------------- */
  const runOperation = useCallback(
    async (
      request: PlanningHierarchyOperationRequest,
    ): Promise<{ ok: boolean }> => {
      setBusy(true);
      setNotice(null);
      try {
        const res = await api.planningApplyDraftHierarchyOperation(
          conversationId,
          messageId,
          request,
        );
        setPlan(res.plan);
        setRevision(res.proposal_revision);
        setPending(null);
        return { ok: true };
      } catch (e: any) {
        if (e?.status === 409) {
          // Revision / state conflict — refresh, discard the failed op.
          try {
            const res = await api.planningGetDraftHierarchy(conversationId, messageId);
            setPlan(res.plan);
            setRevision(res.proposal_revision);
            setPending(null);
            setNotice(
              "This plan changed elsewhere. I refreshed it—please review and try again.",
            );
          } catch (loadErr: any) {
            setLoadError(loadErr?.message || "Could not refresh this plan.");
          }
          return { ok: false };
        }
        setPending({
          request,
          error: e?.message || "Something went wrong applying that change.",
        });
        return { ok: false };
      } finally {
        setBusy(false);
      }
    },
    [conversationId, messageId],
  );

  const retryPending = useCallback(async () => {
    if (!pending) return;
    await runOperation(pending.request);
  }, [pending, runOperation]);

  const clearPending = useCallback(() => setPending(null), []);

  /* ---- Move: enumerate valid destinations -------------------------- */
  const openMoveModal = useCallback(
    (entity_type: "milestone" | "task" | "required_checkin", entity_id: string) => {
      let current_parent_id = "";
      const options: MoveTargetOption[] = [];
      if (entity_type === "milestone") {
        plan.phases.forEach((ph, pi) => {
          const contains = ph.milestones.some((m) => m.id === entity_id);
          if (contains) current_parent_id = ph.id;
          options.push({ id: ph.id, label: `Phase ${pi + 1} — ${ph.title}` });
        });
      } else if (entity_type === "task") {
        plan.phases.forEach((ph, pi) => {
          ph.milestones.forEach((m, mi) => {
            const contains = m.tasks.some((t) => t.id === entity_id);
            if (contains) current_parent_id = m.id;
            options.push({
              id: m.id,
              label: `Milestone ${pi + 1}.${mi + 1} — ${m.title}`,
            });
          });
        });
      } else {
        plan.phases.forEach((ph, pi) => {
          ph.milestones.forEach((m, mi) => {
            m.tasks.forEach((t, ti) => {
              const contains = t.required_checkins.some((rc) => rc.id === entity_id);
              if (contains) current_parent_id = t.id;
              options.push({
                id: t.id,
                label: `Task ${pi + 1}.${mi + 1}.${ti + 1} — ${t.title}`,
              });
            });
          });
        });
      }
      setMoveState({
        entity_type,
        entity_id,
        current_parent_id,
        options: options.filter((o) => o.id !== current_parent_id),
      });
    },
    [plan],
  );

  const performMoveWithinParent = useCallback(
    async (
      entity_type: PlanningHierarchyEntityType,
      entity_id: string,
      parent_id: string,
      new_position: number,
    ) => {
      const op: PlanningHierarchyOperationRequest = {
        operation_id: createPlanningOperationId(),
        expected_revision: revision,
        action: "move",
        entity_type,
        entity_id,
        parent_id,
        position: new_position,
        values: null,
      };
      await runOperation(op);
    },
    [revision, runOperation],
  );

  const performMoveToOtherParent = useCallback(
    async (destination_parent_id: string) => {
      if (!moveState) return;
      // Compute destination child count from local plan.
      const child_count = countChildrenOfParent(plan, moveState.entity_type, destination_parent_id);
      const op: PlanningHierarchyOperationRequest = {
        operation_id: createPlanningOperationId(),
        expected_revision: revision,
        action: "move",
        entity_type: moveState.entity_type,
        entity_id: moveState.entity_id,
        parent_id: destination_parent_id,
        position: child_count + 1,
        values: null,
      };
      setMoveState(null);
      await runOperation(op);
    },
    [moveState, plan, revision, runOperation],
  );

  /* ---- Remove ------------------------------------------------------- */
  const confirmRemove = useCallback(async () => {
    if (!removeState) return;
    const op: PlanningHierarchyOperationRequest = {
      operation_id: createPlanningOperationId(),
      expected_revision: revision,
      action: "delete",
      entity_type: removeState.entity_type,
      entity_id: removeState.entity_id,
      parent_id: null,
      position: null,
      values: null,
    };
    const res = await runOperation(op);
    if (res.ok) setRemoveState(null);
  }, [removeState, revision, runOperation]);

  /* ---- Copy (duplicate) -------------------------------------------- */
  const duplicateNode = useCallback(
    async (entity_type: "phase" | "milestone" | "task" | "required_checkin", entity_id: string) => {
      const loc = locateNode(plan, entity_type, entity_id);
      if (!loc) return;
      const op: PlanningHierarchyOperationRequest = {
        operation_id: createPlanningOperationId(),
        expected_revision: revision,
        action: "duplicate",
        entity_type,
        entity_id,
        parent_id: loc.parent_id,
        position: loc.index + 2, // one-based, right after the source
        values: null,
      };
      await runOperation(op);
    },
    [plan, revision, runOperation],
  );

  /* ---- Save edit ---------------------------------------------------- */
  const saveEdit = useCallback(async () => {
    if (!editForm) return;
    const values: Record<string, unknown> = {};
    const isChanged = (key: keyof EditFormState["original"]) =>
      editForm[key] !== editForm.original[key];
    if (editForm.entity_type === "plan") {
      if (!editForm.title.trim()) return;
      if (isChanged("title")) values.title = editForm.title.trim();
    } else if (editForm.entity_type === "phase") {
      if (!editForm.title.trim()) return;
      if (isChanged("title")) values.title = editForm.title.trim();
      if (isChanged("description")) values.description = editForm.description.trim() || null;
    } else if (editForm.entity_type === "milestone") {
      if (!editForm.title.trim()) return;
      if (isChanged("title")) values.title = editForm.title.trim();
      if (isChanged("description")) values.description = editForm.description.trim() || null;
      if (isChanged("target_date")) values.target_date = editForm.target_date || null;
    } else if (editForm.entity_type === "task") {
      if (!editForm.title.trim()) return;
      if (isChanged("title")) values.title = editForm.title.trim();
      if (isChanged("description")) values.description = editForm.description.trim() || null;
      if (isChanged("due_date")) values.due_date = editForm.due_date || null;
      if (isChanged("priority")) values.priority = editForm.priority;
    } else if (editForm.entity_type === "required_checkin") {
      if (!editForm.title.trim() || !editForm.prompt.trim()) return;
      if (isChanged("title")) values.title = editForm.title.trim();
      if (isChanged("prompt")) values.prompt = editForm.prompt.trim();
      if (isChanged("cadence")) values.cadence = editForm.cadence;
    }
    if (Object.keys(values).length === 0) {
      setEditForm(null);
      return;
    }
    const op: PlanningHierarchyOperationRequest = {
      operation_id: createPlanningOperationId(),
      expected_revision: revision,
      action: "update",
      entity_type: editForm.entity_type,
      entity_id: editForm.entity_id,
      parent_id: null,
      position: null,
      values,
    };
    const res = await runOperation(op);
    if (res.ok) setEditForm(null);
  }, [editForm, revision, runOperation]);

  /* ---- Save add ----------------------------------------------------- */
  const saveAdd = useCallback(async () => {
    if (!addForm) return;
    const trim = (s: string) => s.trim();
    if (!trim(addForm.title)) return;

    let values: Record<string, unknown>;
    if (addForm.kind === "required_checkin") {
      if (!trim(addForm.prompt)) return;
      values = { title: trim(addForm.title), prompt: trim(addForm.prompt), cadence: addForm.cadence };
    } else if (addForm.kind === "task") {
      if (!trim(addForm.first_checkin_title) || !trim(addForm.prompt)) return;
      values = {
        title: trim(addForm.title),
        description: trim(addForm.description) || null,
        due_date: addForm.due_date || null,
        priority: addForm.priority,
        required_checkins: [
          {
            title: trim(addForm.first_checkin_title),
            prompt: trim(addForm.prompt),
            cadence: addForm.cadence,
          },
        ],
      };
    } else if (addForm.kind === "milestone") {
      if (
        !trim(addForm.first_task_title) ||
        !trim(addForm.first_checkin_title) ||
        !trim(addForm.prompt)
      ) {
        return;
      }
      values = {
        title: trim(addForm.title),
        description: trim(addForm.description) || null,
        target_date: addForm.target_date || null,
        tasks: [
          {
            title: trim(addForm.first_task_title),
            required_checkins: [
              {
                title: trim(addForm.first_checkin_title),
                prompt: trim(addForm.prompt),
                cadence: addForm.cadence,
              },
            ],
          },
        ],
      };
    } else {
      // phase
      if (
        !trim(addForm.first_milestone_title) ||
        !trim(addForm.first_task_title) ||
        !trim(addForm.first_checkin_title) ||
        !trim(addForm.prompt)
      ) {
        return;
      }
      values = {
        title: trim(addForm.title),
        description: trim(addForm.description) || null,
        milestones: [
          {
            title: trim(addForm.first_milestone_title),
            tasks: [
              {
                title: trim(addForm.first_task_title),
                required_checkins: [
                  {
                    title: trim(addForm.first_checkin_title),
                    prompt: trim(addForm.prompt),
                    cadence: addForm.cadence,
                  },
                ],
              },
            ],
          },
        ],
      };
    }

    const op: PlanningHierarchyOperationRequest = {
      operation_id: createPlanningOperationId(),
      expected_revision: revision,
      action: "add",
      entity_type: addForm.kind,
      entity_id: null,
      parent_id: addForm.parent_id,
      position: addForm.parent_child_count + 1,
      values,
    };
    const res = await runOperation(op);
    if (res.ok) setAddForm(null);
  }, [addForm, revision, runOperation]);

  /* ---- Materialize (Add this plan to Hymn) -------------------------- */
  const applyPlan = useCallback(async () => {
    if (!loaded || readOnly) return;
    setApplying(true);
    setApplyError(null);
    try {
      const res = await api.planningMaterialize(conversationId, messageId, revision);
      setAppliedSummary(
        (res && (res as any).result && (res as any).result.summary) ||
          materializedSummary ||
          "Plan added to Hymn.",
      );
      onConversationUpdated((res as any).conversation);
    } catch (e: any) {
      if (e?.status === 409) {
        try {
          const fresh = await api.planningGetDraftHierarchy(conversationId, messageId);
          setPlan(fresh.plan);
          setRevision(fresh.proposal_revision);
          setPending(null);
        } catch {
          /* leave existing plan in place */
        }
        setApplyError(
          "This plan changed. I refreshed it—review it once more before adding it.",
        );
      } else {
        setApplyError(e?.message || "Could not add this plan.");
      }
    } finally {
      setApplying(false);
    }
  }, [
    conversationId,
    loaded,
    materializedSummary,
    messageId,
    onConversationUpdated,
    readOnly,
    revision,
  ]);

  /* ---- Render ------------------------------------------------------- */

  if (currentlyApplying) {
    return (
      <View style={styles.card} testID={`planning-draft-${messageId}`}>
        <View style={styles.headerRow}>
          <Ionicons name="sparkles" size={16} color={colors.brandPrimary} />
          <Text style={styles.headerTitle}>{plan.title || "Draft plan"}</Text>
        </View>
        <View style={styles.rowGap}>
          <ActivityIndicator size="small" color={colors.brandPrimary} />
          <Text style={styles.mutedText}>Adding this plan to Hymn…</Text>
        </View>
      </View>
    );
  }

  if (alreadyApplied) {
    return (
      <View style={styles.card} testID={`planning-draft-${messageId}`}>
        <View style={styles.headerRow}>
          <Ionicons name="checkmark-circle" size={18} color={colors.success} />
          <Text style={styles.headerTitle}>{plan.title || "Plan"}</Text>
        </View>
        <Text style={styles.appliedText}>{appliedSummary || "Plan added to Hymn."}</Text>
        <RenderPlanReadOnly plan={plan} />
      </View>
    );
  }

  if (loading && !loaded) {
    return (
      <View style={styles.card} testID={`planning-draft-${messageId}`}>
        <View style={styles.rowGap} testID={`planning-draft-loading-${messageId}`}>
          <ActivityIndicator size="small" color={colors.brandPrimary} />
          <Text style={styles.mutedText}>Loading this plan…</Text>
        </View>
      </View>
    );
  }

  if (loadError && !loaded) {
    return (
      <View style={styles.card} testID={`planning-draft-${messageId}`}>
        <Text style={styles.errorText}>{loadError}</Text>
        <Pressable onPress={reloadHierarchy} style={styles.secondaryBtn}>
          <Text style={styles.secondaryBtnText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.card} testID={`planning-draft-${messageId}`}>
      <View style={styles.headerRow}>
        <Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.headerLabel}>PLAN</Text>
          <Text style={styles.headerTitle}>{plan.title || "Untitled plan"}</Text>
        </View>
        <Pressable
          onPress={() => openEditForm("plan", { id: plan.id, title: plan.title })}
          disabled={busy || applying}
          hitSlop={8}
          testID={`planning-node-edit-${plan.id}`}
        >
          <Ionicons
            name="pencil"
            size={16}
            color={busy || applying ? colors.onSurfaceTertiary : colors.onSurfaceSecondary}
          />
        </Pressable>
      </View>

      {materializationState === "failed" ? (
        <Text style={styles.inlineWarning}>
          The last attempt did not finish. Review the plan and try again.
        </Text>
      ) : null}
      {notice ? <Text style={styles.inlineNotice}>{notice}</Text> : null}

      {plan.phases.map((phase, phaseIndex) => (
        <PhaseCard
          key={phase.id}
          phase={phase}
          phaseIndex={phaseIndex}
          totalPhases={plan.phases.length}
          planId={plan.id}
          collapsed={!!collapsedPhaseIds[phase.id]}
          onToggle={() =>
            setCollapsedPhaseIds((prev) => ({ ...prev, [phase.id]: !prev[phase.id] }))
          }
          disabled={busy || applying}
          onEdit={(entity_type, ctx) => openEditForm(entity_type, ctx)}
          onCopy={duplicateNode}
          onRemove={(entity_type, entity_id, title) =>
            setRemoveState({
              entity_type,
              entity_id,
              title,
              will_cascade:
                entity_type === "phase" ||
                entity_type === "milestone" ||
                entity_type === "task",
            })
          }
          onMoveWithin={performMoveWithinParent}
          onOpenMove={openMoveModal}
          onAdd={(kind, parent_id, parent_child_count) =>
            setAddForm(makeInitialAddForm(kind, parent_id, parent_child_count))
          }
        />
      ))}

      <Pressable
        onPress={() =>
          setAddForm(makeInitialAddForm("phase", plan.id, plan.phases.length))
        }
        disabled={busy || applying}
        style={[styles.addRow, (busy || applying) && styles.disabled]}
        testID={`planning-add-phase-${messageId}`}
      >
        <Ionicons name="add-circle-outline" size={16} color={colors.brandPrimary} />
        <Text style={styles.addRowText}>Add phase</Text>
      </Pressable>

      {pending ? (
        <View style={styles.pendingBanner} testID={`planning-draft-error-${messageId}`}>
          <Ionicons name="alert-circle" size={14} color={colors.error} />
          <View style={{ flex: 1 }}>
            <Text style={styles.errorText}>{pending.error}</Text>
          </View>
          <Pressable
            onPress={retryPending}
            disabled={busy}
            style={styles.retryBtn}
            testID={`planning-operation-retry-${messageId}`}
          >
            <Text style={styles.retryBtnText}>Retry</Text>
          </Pressable>
          <Pressable onPress={clearPending} disabled={busy} hitSlop={8}>
            <Ionicons name="close" size={16} color={colors.onSurfaceSecondary} />
          </Pressable>
        </View>
      ) : null}

      {applyError ? <Text style={styles.inlineWarning}>{applyError}</Text> : null}

      <Pressable
        onPress={applyPlan}
        disabled={applying || busy || !loaded}
        style={[styles.applyBtn, (applying || busy) && styles.disabled]}
        testID={`planning-draft-apply-${messageId}`}
      >
        {applying ? (
          <ActivityIndicator color={colors.onBrandPrimary} size="small" />
        ) : (
          <>
            <Ionicons name="checkmark" size={16} color={colors.onBrandPrimary} />
            <Text style={styles.applyBtnText}>Add this plan to Hymn</Text>
          </>
        )}
      </Pressable>

      {/* Edit modal */}
      <EditFormModal
        visible={!!editForm}
        state={editForm}
        setState={setEditForm}
        busy={busy}
        onCancel={() => setEditForm(null)}
        onSave={saveEdit}
      />

      {/* Add modal */}
      <AddFormModal
        state={addForm}
        setState={setAddForm}
        busy={busy}
        onCancel={() => setAddForm(null)}
        onSave={saveAdd}
      />

      {/* Move-to modal */}
      <MoveTargetModal
        state={moveState}
        busy={busy}
        onCancel={() => setMoveState(null)}
        onPick={performMoveToOtherParent}
      />

      {/* Remove confirmation */}
      <ConfirmModal
        visible={!!removeState}
        title={removeState ? `Remove “${removeState.title}” from this draft plan?` : ""}
        message={
          removeState?.will_cascade
            ? "Its contained items will be removed too."
            : "This will remove it from the draft only. The permanent plan is not affected."
        }
        confirmLabel="Remove"
        danger
        busy={busy}
        error={pending?.error && removeState ? pending.error : null}
        onCancel={() => setRemoveState(null)}
        onConfirm={confirmRemove}
      />
    </View>
  );

  /* ---- helpers scoped to component --------------------------------- */
  function openEditForm(
    entity_type: EditFormState["entity_type"],
    ctx: {
      id: string;
      title: string;
      description?: string | null;
      target_date?: string | null;
      due_date?: string | null;
      priority?: "low" | "medium" | "high";
      prompt?: string;
      cadence?: PlanningRequiredCheckinDraft["cadence"];
    },
  ) {
    const base: EditFormState = {
      entity_type,
      entity_id: ctx.id,
      title: ctx.title || "",
      description: ctx.description || "",
      target_date: ctx.target_date || "",
      due_date: ctx.due_date || "",
      priority: ctx.priority || "medium",
      prompt: ctx.prompt || "",
      cadence: ctx.cadence || "weekly",
      original: {
        title: ctx.title || "",
        description: ctx.description || "",
        target_date: ctx.target_date || "",
        due_date: ctx.due_date || "",
        priority: ctx.priority || "medium",
        prompt: ctx.prompt || "",
        cadence: ctx.cadence || "weekly",
      },
    };
    setEditForm(base);
  }
}

/* -------------------------------------------------------------------- */
/*  Helpers                                                              */
/* -------------------------------------------------------------------- */

function makeInitialAddForm(
  kind: AddFormKind, parent_id: string, parent_child_count: number,
): AddFormState {
  return {
    kind,
    parent_id,
    parent_child_count,
    title: "",
    description: "",
    target_date: "",
    due_date: "",
    priority: "medium",
    first_milestone_title: "",
    first_task_title: "",
    first_checkin_title: "",
    prompt: "",
    cadence: "weekly",
  };
}

function countChildrenOfParent(
  plan: PlanningPlanDraft,
  entity_type: "milestone" | "task" | "required_checkin",
  parent_id: string,
): number {
  if (entity_type === "milestone") {
    const ph = plan.phases.find((p) => p.id === parent_id);
    return ph ? ph.milestones.length : 0;
  }
  if (entity_type === "task") {
    for (const ph of plan.phases) {
      const m = ph.milestones.find((mm) => mm.id === parent_id);
      if (m) return m.tasks.length;
    }
    return 0;
  }
  for (const ph of plan.phases) {
    for (const m of ph.milestones) {
      const t = m.tasks.find((tt) => tt.id === parent_id);
      if (t) return t.required_checkins.length;
    }
  }
  return 0;
}

function locateNode(
  plan: PlanningPlanDraft,
  entity_type: "phase" | "milestone" | "task" | "required_checkin",
  entity_id: string,
): { parent_id: string; index: number } | null {
  if (entity_type === "phase") {
    const idx = plan.phases.findIndex((p) => p.id === entity_id);
    return idx >= 0 ? { parent_id: plan.id, index: idx } : null;
  }
  for (const ph of plan.phases) {
    if (entity_type === "milestone") {
      const idx = ph.milestones.findIndex((m) => m.id === entity_id);
      if (idx >= 0) return { parent_id: ph.id, index: idx };
      continue;
    }
    for (const m of ph.milestones) {
      if (entity_type === "task") {
        const idx = m.tasks.findIndex((t) => t.id === entity_id);
        if (idx >= 0) return { parent_id: m.id, index: idx };
        continue;
      }
      for (const t of m.tasks) {
        const idx = t.required_checkins.findIndex((rc) => rc.id === entity_id);
        if (idx >= 0) return { parent_id: t.id, index: idx };
      }
    }
  }
  return null;
}

/* -------------------------------------------------------------------- */
/*  Sub-components                                                       */
/* -------------------------------------------------------------------- */

type PhaseCardProps = {
  phase: PlanningPhaseDraft;
  phaseIndex: number;
  totalPhases: number;
  planId: string;
  collapsed: boolean;
  onToggle: () => void;
  disabled: boolean;
  onEdit: (
    entity_type: "plan" | "phase" | "milestone" | "task" | "required_checkin",
    ctx: {
      id: string; title: string; description?: string | null; target_date?: string | null;
      due_date?: string | null; priority?: "low" | "medium" | "high";
      prompt?: string; cadence?: PlanningRequiredCheckinDraft["cadence"];
    },
  ) => void;
  onCopy: (entity_type: "phase" | "milestone" | "task" | "required_checkin", id: string) => void;
  onRemove: (entity_type: PlanningHierarchyEntityType, id: string, title: string) => void;
  onMoveWithin: (
    entity_type: PlanningHierarchyEntityType, id: string, parent_id: string, new_position: number,
  ) => void;
  onOpenMove: (
    entity_type: "milestone" | "task" | "required_checkin", id: string,
  ) => void;
  onAdd: (kind: AddFormKind, parent_id: string, parent_child_count: number) => void;
};

function PhaseCard(props: PhaseCardProps) {
  const {
    phase, phaseIndex, totalPhases, planId, collapsed, onToggle, disabled,
    onEdit, onCopy, onRemove, onMoveWithin, onOpenMove, onAdd,
  } = props;
  return (
    <View style={styles.phaseCard} testID={`planning-node-${phase.id}`}>
      <View style={styles.phaseHeader}>
        <Pressable onPress={onToggle} hitSlop={8} style={{ flexDirection: "row", alignItems: "center", gap: 6, flex: 1 }}>
          <Ionicons name={collapsed ? "chevron-forward" : "chevron-down"} size={16} color={colors.onSurfaceSecondary} />
          <Text style={styles.phaseLabel}>Phase {phaseIndex + 1}</Text>
          <Text style={styles.phaseTitle} numberOfLines={2}>{phase.title}</Text>
        </Pressable>
        <NodeActions
          disabled={disabled}
          nodeId={phase.id}
          isFirst={phaseIndex === 0}
          isLast={phaseIndex === totalPhases - 1}
          onEdit={() => onEdit("phase", { id: phase.id, title: phase.title, description: phase.description })}
          onCopy={() => onCopy("phase", phase.id)}
          onRemove={() => onRemove("phase", phase.id, phase.title)}
          onUp={() => onMoveWithin("phase", phase.id, planId, phaseIndex /* zero-based → position i */)}
          onDown={() => onMoveWithin("phase", phase.id, planId, phaseIndex + 2)}
          canMove={false}
        />
      </View>
      {phase.description ? (
        <Text style={styles.phaseDescription}>{phase.description}</Text>
      ) : null}
      {!collapsed ? (
        <View style={styles.phaseBody}>
          {phase.milestones.map((m, mi) => (
            <MilestoneCard
              key={m.id}
              milestone={m}
              phaseIndex={phaseIndex}
              milestoneIndex={mi}
              parentPhaseId={phase.id}
              totalMilestones={phase.milestones.length}
              disabled={disabled}
              onEdit={onEdit}
              onCopy={onCopy}
              onRemove={onRemove}
              onMoveWithin={onMoveWithin}
              onOpenMove={onOpenMove}
              onAdd={onAdd}
            />
          ))}
          <Pressable
            onPress={() => onAdd("milestone", phase.id, phase.milestones.length)}
            disabled={disabled}
            style={[styles.addRow, disabled && styles.disabled]}
          >
            <Ionicons name="add-circle-outline" size={14} color={colors.brandPrimary} />
            <Text style={styles.addRowText}>Add milestone</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

type MilestoneCardProps = {
  milestone: PlanningMilestoneDraft;
  phaseIndex: number;
  milestoneIndex: number;
  parentPhaseId: string;
  totalMilestones: number;
  disabled: boolean;
  onEdit: PhaseCardProps["onEdit"];
  onCopy: PhaseCardProps["onCopy"];
  onRemove: PhaseCardProps["onRemove"];
  onMoveWithin: PhaseCardProps["onMoveWithin"];
  onOpenMove: PhaseCardProps["onOpenMove"];
  onAdd: PhaseCardProps["onAdd"];
};

function MilestoneCard(props: MilestoneCardProps) {
  const {
    milestone, phaseIndex, milestoneIndex, parentPhaseId, totalMilestones, disabled,
    onEdit, onCopy, onRemove, onMoveWithin, onOpenMove, onAdd,
  } = props;
  return (
    <View style={styles.milestoneCard} testID={`planning-node-${milestone.id}`}>
      <View style={styles.milestoneHeader}>
        <View style={{ flex: 1 }}>
          <Text style={styles.milestoneLabel}>
            Milestone {phaseIndex + 1}.{milestoneIndex + 1}
          </Text>
          <Text style={styles.milestoneTitle} numberOfLines={2}>{milestone.title}</Text>
          {milestone.target_date ? (
            <Text style={styles.metaText}>Target date: {milestone.target_date}</Text>
          ) : null}
          {milestone.description ? (
            <Text style={styles.milestoneDescription}>{milestone.description}</Text>
          ) : null}
        </View>
        <NodeActions
          disabled={disabled}
          nodeId={milestone.id}
          isFirst={milestoneIndex === 0}
          isLast={milestoneIndex === totalMilestones - 1}
          canMove
          onEdit={() =>
            onEdit("milestone", {
              id: milestone.id,
              title: milestone.title,
              description: milestone.description,
              target_date: milestone.target_date,
            })
          }
          onCopy={() => onCopy("milestone", milestone.id)}
          onRemove={() => onRemove("milestone", milestone.id, milestone.title)}
          onUp={() => onMoveWithin("milestone", milestone.id, parentPhaseId, milestoneIndex)}
          onDown={() => onMoveWithin("milestone", milestone.id, parentPhaseId, milestoneIndex + 2)}
          onMove={() => onOpenMove("milestone", milestone.id)}
        />
      </View>
      <View style={styles.taskBody}>
        {milestone.tasks.map((t, ti) => (
          <TaskCard
            key={t.id}
            task={t}
            phaseIndex={phaseIndex}
            milestoneIndex={milestoneIndex}
            taskIndex={ti}
            parentMilestoneId={milestone.id}
            totalTasks={milestone.tasks.length}
            disabled={disabled}
            onEdit={onEdit}
            onCopy={onCopy}
            onRemove={onRemove}
            onMoveWithin={onMoveWithin}
            onOpenMove={onOpenMove}
            onAdd={onAdd}
          />
        ))}
        <Pressable
          onPress={() => onAdd("task", milestone.id, milestone.tasks.length)}
          disabled={disabled}
          style={[styles.addRow, disabled && styles.disabled]}
        >
          <Ionicons name="add-circle-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.addRowText}>Add task</Text>
        </Pressable>
      </View>
    </View>
  );
}

type TaskCardProps = {
  task: PlanningTaskDraft;
  phaseIndex: number;
  milestoneIndex: number;
  taskIndex: number;
  parentMilestoneId: string;
  totalTasks: number;
  disabled: boolean;
  onEdit: PhaseCardProps["onEdit"];
  onCopy: PhaseCardProps["onCopy"];
  onRemove: PhaseCardProps["onRemove"];
  onMoveWithin: PhaseCardProps["onMoveWithin"];
  onOpenMove: PhaseCardProps["onOpenMove"];
  onAdd: PhaseCardProps["onAdd"];
};

function TaskCard(props: TaskCardProps) {
  const {
    task, phaseIndex, milestoneIndex, taskIndex, parentMilestoneId, totalTasks,
    disabled, onEdit, onCopy, onRemove, onMoveWithin, onOpenMove, onAdd,
  } = props;
  return (
    <View style={styles.taskCard} testID={`planning-node-${task.id}`}>
      <View style={styles.taskHeader}>
        <View style={{ flex: 1 }}>
          <Text style={styles.taskLabel}>
            Task {phaseIndex + 1}.{milestoneIndex + 1}.{taskIndex + 1}
          </Text>
          <Text style={styles.taskTitle} numberOfLines={2}>{task.title}</Text>
          <View style={styles.taskMetaRow}>
            {task.priority ? (
              <Text style={styles.priorityChip}>{titleCase(task.priority)}</Text>
            ) : null}
            {task.due_date ? (
              <Text style={styles.metaText}>Due {task.due_date}</Text>
            ) : null}
          </View>
          {task.description ? (
            <Text style={styles.taskDescription}>{task.description}</Text>
          ) : null}
        </View>
        <NodeActions
          disabled={disabled}
          nodeId={task.id}
          isFirst={taskIndex === 0}
          isLast={taskIndex === totalTasks - 1}
          canMove
          onEdit={() =>
            onEdit("task", {
              id: task.id, title: task.title, description: task.description,
              due_date: task.due_date, priority: task.priority,
            })
          }
          onCopy={() => onCopy("task", task.id)}
          onRemove={() => onRemove("task", task.id, task.title)}
          onUp={() => onMoveWithin("task", task.id, parentMilestoneId, taskIndex)}
          onDown={() => onMoveWithin("task", task.id, parentMilestoneId, taskIndex + 2)}
          onMove={() => onOpenMove("task", task.id)}
        />
      </View>
      <View style={styles.checkinBody}>
        {task.required_checkins.map((rc, ri) => (
          <View key={rc.id} style={styles.checkinRow} testID={`planning-node-${rc.id}`}>
            <View style={{ flex: 1 }}>
              <Text style={styles.checkinLabel}>Check-in</Text>
              <Text style={styles.checkinTitle}>{rc.title}</Text>
              <Text style={styles.checkinPrompt}>“{rc.prompt}”</Text>
              <Text style={styles.metaText}>{titleCase(rc.cadence)}</Text>
            </View>
            <NodeActions
              disabled={disabled}
              nodeId={rc.id}
              isFirst={ri === 0}
              isLast={ri === task.required_checkins.length - 1}
              canMove
              onEdit={() =>
                onEdit("required_checkin", {
                  id: rc.id, title: rc.title, prompt: rc.prompt, cadence: rc.cadence,
                })
              }
              onCopy={() => onCopy("required_checkin", rc.id)}
              onRemove={() => onRemove("required_checkin", rc.id, rc.title)}
              onUp={() => onMoveWithin("required_checkin", rc.id, task.id, ri)}
              onDown={() => onMoveWithin("required_checkin", rc.id, task.id, ri + 2)}
              onMove={() => onOpenMove("required_checkin", rc.id)}
            />
          </View>
        ))}
        <Pressable
          onPress={() => onAdd("required_checkin", task.id, task.required_checkins.length)}
          disabled={disabled}
          style={[styles.addRow, disabled && styles.disabled]}
        >
          <Ionicons name="add-circle-outline" size={14} color={colors.brandPrimary} />
          <Text style={styles.addRowText}>Add check-in</Text>
        </Pressable>
      </View>
    </View>
  );
}

type NodeActionsProps = {
  disabled: boolean;
  nodeId: string;
  isFirst: boolean;
  isLast: boolean;
  canMove: boolean;
  onEdit: () => void;
  onCopy: () => void;
  onRemove: () => void;
  onUp: () => void;
  onDown: () => void;
  onMove?: () => void;
};

function NodeActions(props: NodeActionsProps) {
  const { disabled, nodeId, isFirst, isLast, canMove, onEdit, onCopy, onRemove, onUp, onDown, onMove } = props;
  return (
    <View style={styles.actionsRow}>
      <Pressable
        onPress={onUp}
        disabled={disabled || isFirst}
        hitSlop={6}
        style={[styles.iconBtn, (disabled || isFirst) && styles.iconBtnDisabled]}
        testID={`planning-node-up-${nodeId}`}
      >
        <Ionicons
          name="chevron-up"
          size={14}
          color={disabled || isFirst ? colors.onSurfaceTertiary : colors.onSurfaceSecondary}
        />
      </Pressable>
      <Pressable
        onPress={onDown}
        disabled={disabled || isLast}
        hitSlop={6}
        style={[styles.iconBtn, (disabled || isLast) && styles.iconBtnDisabled]}
        testID={`planning-node-down-${nodeId}`}
      >
        <Ionicons
          name="chevron-down"
          size={14}
          color={disabled || isLast ? colors.onSurfaceTertiary : colors.onSurfaceSecondary}
        />
      </Pressable>
      {canMove && onMove ? (
        <Pressable
          onPress={onMove}
          disabled={disabled}
          hitSlop={6}
          style={[styles.iconBtn, disabled && styles.iconBtnDisabled]}
          testID={`planning-node-move-${nodeId}`}
        >
          <Ionicons
            name="git-branch-outline"
            size={14}
            color={disabled ? colors.onSurfaceTertiary : colors.onSurfaceSecondary}
          />
        </Pressable>
      ) : null}
      <Pressable
        onPress={onEdit}
        disabled={disabled}
        hitSlop={6}
        style={[styles.iconBtn, disabled && styles.iconBtnDisabled]}
        testID={`planning-node-edit-${nodeId}`}
      >
        <Ionicons name="pencil" size={14} color={disabled ? colors.onSurfaceTertiary : colors.onSurfaceSecondary} />
      </Pressable>
      <Pressable
        onPress={onCopy}
        disabled={disabled}
        hitSlop={6}
        style={[styles.iconBtn, disabled && styles.iconBtnDisabled]}
        testID={`planning-node-copy-${nodeId}`}
      >
        <Ionicons name="copy-outline" size={14} color={disabled ? colors.onSurfaceTertiary : colors.onSurfaceSecondary} />
      </Pressable>
      <Pressable
        onPress={onRemove}
        disabled={disabled}
        hitSlop={6}
        style={[styles.iconBtn, disabled && styles.iconBtnDisabled]}
        testID={`planning-node-remove-${nodeId}`}
      >
        <Ionicons name="trash-outline" size={14} color={disabled ? colors.onSurfaceTertiary : colors.error} />
      </Pressable>
    </View>
  );
}

/* -------------------------------------------------------------------- */
/*  Read-only render                                                     */
/* -------------------------------------------------------------------- */

function RenderPlanReadOnly({ plan }: { plan: PlanningPlanDraft }) {
  return (
    <View>
      {plan.phases.map((phase, pi) => (
        <View key={phase.id} style={styles.phaseCard}>
          <Text style={styles.phaseLabel}>Phase {pi + 1}</Text>
          <Text style={styles.phaseTitle}>{phase.title}</Text>
          {phase.milestones.map((m, mi) => (
            <View key={m.id} style={styles.milestoneCard}>
              <Text style={styles.milestoneLabel}>Milestone {pi + 1}.{mi + 1}</Text>
              <Text style={styles.milestoneTitle}>{m.title}</Text>
              {m.tasks.map((t, ti) => (
                <View key={t.id} style={styles.taskCard}>
                  <Text style={styles.taskLabel}>Task {pi + 1}.{mi + 1}.{ti + 1}</Text>
                  <Text style={styles.taskTitle}>{t.title}</Text>
                  {t.required_checkins.map((rc) => (
                    <View key={rc.id} style={styles.checkinRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.checkinLabel}>Check-in</Text>
                        <Text style={styles.checkinTitle}>{rc.title}</Text>
                        <Text style={styles.checkinPrompt}>“{rc.prompt}”</Text>
                        <Text style={styles.metaText}>{titleCase(rc.cadence)}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              ))}
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}

/* -------------------------------------------------------------------- */
/*  Modals                                                                */
/* -------------------------------------------------------------------- */

function EditFormModal({
  visible, state, setState, busy, onCancel, onSave,
}: {
  visible: boolean;
  state: EditFormState | null;
  setState: React.Dispatch<React.SetStateAction<EditFormState | null>>;
  busy: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  if (!state) return null;
  const t = state.entity_type;
  const canSave =
    !!state.title.trim() && (t !== "required_checkin" || !!state.prompt.trim());
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.modalCard}>
          <ScrollView>
            <Text style={styles.modalTitle}>Edit {titleCase(t.replace("_", " "))}</Text>
            <LabelledInput
              label={t === "required_checkin" ? "Check-in name" : "Title"}
              value={state.title}
              onChangeText={(v) => setState((s) => (s ? { ...s, title: v } : s))}
            />
            {t === "phase" || t === "milestone" || t === "task" ? (
              <LabelledInput
                label="Description"
                value={state.description}
                onChangeText={(v) => setState((s) => (s ? { ...s, description: v } : s))}
                multiline
              />
            ) : null}
            {t === "milestone" ? (
              <View style={styles.field}>
                <Text style={styles.fieldLabel}>Target date</Text>
                <DateTimeField
                  mode="date"
                  value={state.target_date}
                  onChange={(v) => setState((s) => (s ? { ...s, target_date: v } : s))}
                  clearable
                />
              </View>
            ) : null}
            {t === "task" ? (
              <>
                <View style={styles.field}>
                  <Text style={styles.fieldLabel}>Due date</Text>
                  <DateTimeField
                    mode="date"
                    value={state.due_date}
                    onChange={(v) => setState((s) => (s ? { ...s, due_date: v } : s))}
                    clearable
                  />
                </View>
                <View style={styles.field}>
                  <Text style={styles.fieldLabel}>Priority</Text>
                  <ChoiceChips
                    choices={PRIORITY_CHOICES}
                    value={state.priority}
                    onChange={(v) => setState((s) => (s ? { ...s, priority: v } : s))}
                  />
                </View>
              </>
            ) : null}
            {t === "required_checkin" ? (
              <>
                <LabelledInput
                  label="What should Hymn ask?"
                  value={state.prompt}
                  onChangeText={(v) => setState((s) => (s ? { ...s, prompt: v } : s))}
                  multiline
                />
                <View style={styles.field}>
                  <Text style={styles.fieldLabel}>Cadence</Text>
                  <ChoiceChips
                    choices={CADENCE_CHOICES}
                    value={state.cadence}
                    onChange={(v) => setState((s) => (s ? { ...s, cadence: v } : s))}
                  />
                </View>
              </>
            ) : null}
          </ScrollView>
          <View style={styles.modalRow}>
            <Pressable onPress={onCancel} disabled={busy} style={[styles.btn, styles.btnSecondary]}>
              <Text style={styles.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onSave}
              disabled={busy || !canSave}
              style={[styles.btn, styles.btnPrimary, (busy || !canSave) && styles.disabled]}
            >
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.btnPrimaryText}>Save</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function AddFormModal({
  state, setState, busy, onCancel, onSave,
}: {
  state: AddFormState | null;
  setState: React.Dispatch<React.SetStateAction<AddFormState | null>>;
  busy: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  if (!state) return null;
  const kind = state.kind;
  const trim = (v: string) => v.trim();
  const canSave = (() => {
    if (!trim(state.title)) return false;
    if (kind === "required_checkin") return !!trim(state.prompt);
    if (kind === "task")
      return !!trim(state.first_checkin_title) && !!trim(state.prompt);
    if (kind === "milestone")
      return (
        !!trim(state.first_task_title) &&
        !!trim(state.first_checkin_title) &&
        !!trim(state.prompt)
      );
    if (kind === "phase")
      return (
        !!trim(state.first_milestone_title) &&
        !!trim(state.first_task_title) &&
        !!trim(state.first_checkin_title) &&
        !!trim(state.prompt)
      );
    return false;
  })();
  const heading =
    kind === "phase" ? "Add phase" :
    kind === "milestone" ? "Add milestone" :
    kind === "task" ? "Add task" : "Add check-in";
  const nameLabel =
    kind === "phase" ? "Phase name" :
    kind === "milestone" ? "Milestone name" :
    kind === "task" ? "Task name" : "Check-in name";
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.modalCard}>
          <ScrollView>
            <Text style={styles.modalTitle}>{heading}</Text>
            <LabelledInput
              label={nameLabel}
              value={state.title}
              onChangeText={(v) => setState((s) => (s ? { ...s, title: v } : s))}
            />
            {kind === "phase" || kind === "milestone" || kind === "task" ? (
              <LabelledInput
                label={kind === "phase" ? "Phase description (optional)" : "Description (optional)"}
                value={state.description}
                onChangeText={(v) => setState((s) => (s ? { ...s, description: v } : s))}
                multiline
              />
            ) : null}
            {kind === "milestone" ? (
              <View style={styles.field}>
                <Text style={styles.fieldLabel}>Target date (optional)</Text>
                <DateTimeField
                  mode="date"
                  value={state.target_date}
                  onChange={(v) => setState((s) => (s ? { ...s, target_date: v } : s))}
                  clearable
                />
              </View>
            ) : null}
            {kind === "task" ? (
              <>
                <View style={styles.field}>
                  <Text style={styles.fieldLabel}>Due date (optional)</Text>
                  <DateTimeField
                    mode="date"
                    value={state.due_date}
                    onChange={(v) => setState((s) => (s ? { ...s, due_date: v } : s))}
                    clearable
                  />
                </View>
                <View style={styles.field}>
                  <Text style={styles.fieldLabel}>Priority</Text>
                  <ChoiceChips
                    choices={PRIORITY_CHOICES}
                    value={state.priority}
                    onChange={(v) => setState((s) => (s ? { ...s, priority: v } : s))}
                  />
                </View>
              </>
            ) : null}
            {kind === "phase" ? (
              <LabelledInput
                label="First milestone name"
                value={state.first_milestone_title}
                onChangeText={(v) => setState((s) => (s ? { ...s, first_milestone_title: v } : s))}
              />
            ) : null}
            {kind === "phase" || kind === "milestone" ? (
              <LabelledInput
                label="First task name"
                value={state.first_task_title}
                onChangeText={(v) => setState((s) => (s ? { ...s, first_task_title: v } : s))}
              />
            ) : null}
            {kind === "phase" || kind === "milestone" || kind === "task" ? (
              <LabelledInput
                label="First check-in name"
                value={state.first_checkin_title}
                onChangeText={(v) => setState((s) => (s ? { ...s, first_checkin_title: v } : s))}
              />
            ) : null}
            <LabelledInput
              label="What should Hymn ask?"
              value={state.prompt}
              onChangeText={(v) => setState((s) => (s ? { ...s, prompt: v } : s))}
              multiline
            />
            <View style={styles.field}>
              <Text style={styles.fieldLabel}>Check-in cadence</Text>
              <ChoiceChips
                choices={CADENCE_CHOICES}
                value={state.cadence}
                onChange={(v) => setState((s) => (s ? { ...s, cadence: v } : s))}
              />
            </View>
          </ScrollView>
          <View style={styles.modalRow}>
            <Pressable onPress={onCancel} disabled={busy} style={[styles.btn, styles.btnSecondary]}>
              <Text style={styles.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onSave}
              disabled={busy || !canSave}
              style={[styles.btn, styles.btnPrimary, (busy || !canSave) && styles.disabled]}
            >
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.btnPrimaryText}>Add</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function MoveTargetModal({
  state, busy, onCancel, onPick,
}: {
  state: MoveState | null;
  busy: boolean;
  onCancel: () => void;
  onPick: (parent_id: string) => void;
}) {
  if (!state) return null;
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.modalTitle}>Move to…</Text>
          <ScrollView style={{ maxHeight: 320 }}>
            {state.options.length === 0 ? (
              <Text style={styles.mutedText}>Nowhere else to move this yet.</Text>
            ) : (
              state.options.map((opt) => (
                <Pressable
                  key={opt.id}
                  onPress={() => onPick(opt.id)}
                  disabled={busy}
                  style={styles.destRow}
                >
                  <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceSecondary} />
                  <Text style={styles.destText}>{opt.label}</Text>
                </Pressable>
              ))
            )}
          </ScrollView>
          <View style={styles.modalRow}>
            <Pressable onPress={onCancel} disabled={busy} style={[styles.btn, styles.btnSecondary]}>
              <Text style={styles.btnSecondaryText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* -------------------------------------------------------------------- */
/*  Small inputs                                                          */
/* -------------------------------------------------------------------- */

function LabelledInput({
  label, value, onChangeText, multiline,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  multiline?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        style={[styles.input, multiline && { minHeight: 60, textAlignVertical: "top" }]}
        multiline={multiline}
        placeholderTextColor={colors.onSurfaceTertiary}
      />
    </View>
  );
}

function ChoiceChips<T extends string>({
  choices, value, onChange,
}: {
  choices: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <View style={styles.chipsRow}>
      {choices.map((c) => (
        <Pressable
          key={c.value}
          onPress={() => onChange(c.value)}
          style={[styles.chip, value === c.value && styles.chipActive]}
        >
          <Text style={[styles.chipText, value === c.value && styles.chipTextActive]}>{c.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function titleCase(s: string): string {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/* -------------------------------------------------------------------- */
/*  Styles                                                                */
/* -------------------------------------------------------------------- */

const styles = StyleSheet.create({
  card: {
    marginTop: spacing.sm,
    backgroundColor: colors.surface,
    borderColor: colors.brandPrimary,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
    maxWidth: "96%",
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerLabel: {
    fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  headerTitle: {
    fontFamily: fonts.displayBold, fontSize: 15, color: colors.onSurface, fontWeight: "600",
  },
  rowGap: { flexDirection: "row", alignItems: "center", gap: 8 },
  mutedText: { color: colors.onSurfaceSecondary, fontSize: 13 },
  inlineNotice: {
    color: colors.onSurfaceSecondary, fontSize: 13, fontStyle: "italic",
    backgroundColor: colors.brandTertiary,
    padding: spacing.sm, borderRadius: radius.sm,
  },
  inlineWarning: {
    color: colors.warning, fontSize: 13, backgroundColor: colors.warning + "18",
    padding: spacing.sm, borderRadius: radius.sm,
  },
  errorText: { color: colors.error, fontSize: 12, flex: 1 },
  appliedText: { color: colors.success, fontSize: 13, fontWeight: "500" },

  phaseCard: {
    marginTop: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    borderLeftWidth: 3, borderLeftColor: colors.brandPrimary,
    gap: spacing.xs,
  },
  phaseHeader: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  phaseLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5, textTransform: "uppercase" },
  phaseTitle: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onSurface, fontWeight: "600", flex: 1 },
  phaseDescription: { fontSize: 12, color: colors.onSurfaceSecondary, marginLeft: 22 },
  phaseBody: { marginTop: spacing.sm, gap: spacing.xs, marginLeft: spacing.sm },

  milestoneCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    padding: spacing.sm,
    borderLeftWidth: 2, borderLeftColor: colors.brandSecondary,
    gap: 2,
  },
  milestoneHeader: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  milestoneLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.2, textTransform: "uppercase" },
  milestoneTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  milestoneDescription: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  taskBody: { marginTop: spacing.xs, gap: 4, marginLeft: spacing.sm },

  taskCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.sm,
    borderLeftWidth: 2, borderLeftColor: colors.brandTertiary,
    gap: 2,
  },
  taskHeader: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  taskLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.2, textTransform: "uppercase" },
  taskTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  taskDescription: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  taskMetaRow: { flexDirection: "row", gap: 6, marginTop: 2, alignItems: "center", flexWrap: "wrap" },
  priorityChip: {
    fontSize: 10, color: colors.onBrandTertiary, backgroundColor: colors.brandTertiary,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill, overflow: "hidden",
  },
  metaText: { fontSize: 11, color: colors.onSurfaceSecondary },
  checkinBody: { marginTop: spacing.xs, gap: 4, marginLeft: spacing.sm },

  checkinRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: colors.surface, borderRadius: radius.sm,
    padding: spacing.sm, borderLeftWidth: 2, borderLeftColor: colors.borderStrong,
  },
  checkinLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.2, textTransform: "uppercase" },
  checkinTitle: { fontSize: 13, color: colors.onSurface, fontWeight: "500" },
  checkinPrompt: { fontSize: 12, color: colors.onSurfaceSecondary, fontStyle: "italic", marginTop: 2 },

  addRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: spacing.xs,
  },
  addRowText: { color: colors.brandPrimary, fontSize: 13, fontWeight: "500" },
  disabled: { opacity: 0.5 },

  actionsRow: { flexDirection: "row", gap: 2, alignItems: "center" },
  iconBtn: {
    padding: 4, borderRadius: radius.sm,
  },
  iconBtnDisabled: { opacity: 0.4 },

  applyBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingVertical: 12, borderRadius: radius.pill,
    marginTop: spacing.sm,
  },
  applyBtnText: { color: colors.onBrandPrimary, fontWeight: "600", fontSize: 14 },

  pendingBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.error + "12", borderRadius: radius.sm, padding: spacing.sm,
  },
  retryBtn: {
    backgroundColor: colors.error, paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: radius.pill,
  },
  retryBtnText: { color: colors.onError, fontSize: 12, fontWeight: "600" },

  backdrop: {
    flex: 1, backgroundColor: "rgba(30,30,28,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  modalCard: {
    width: "100%", maxWidth: 420, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm, maxHeight: "90%",
  },
  modalTitle: {
    fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface,
    fontWeight: "700", marginBottom: spacing.xs,
  },
  modalRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  field: { marginTop: spacing.sm, gap: 4 },
  fieldLabel: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "500" },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    fontSize: 14, color: colors.onSurface,
  },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 2 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
  },
  chipActive: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 12, color: colors.onSurface },
  chipTextActive: { color: colors.onBrandPrimary, fontWeight: "600" },
  destRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10 },
  destText: { fontSize: 14, color: colors.onSurface, flex: 1 },
  btn: { flex: 1, paddingVertical: 10, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  btnSecondary: { backgroundColor: colors.surfaceSecondary },
  btnSecondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "500" },
  btnPrimary: { backgroundColor: colors.brandPrimary },
  btnPrimaryText: { color: colors.onBrandPrimary, fontSize: 14, fontWeight: "600" },
  secondaryBtn: {
    marginTop: spacing.sm, paddingVertical: 10, borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary, alignItems: "center",
  },
  secondaryBtnText: { color: colors.onSurface, fontSize: 14 },
});
