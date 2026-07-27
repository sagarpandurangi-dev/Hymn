import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/lib/api";
import {
  createDraftItem,
  errorMessage,
  isPlanningTargetType,
  moveDraftItem,
  nextActionSummary,
  orderedContextSections,
  planningEmptyState,
  removeDraftItem,
  replaceDraftItem,
  toggleDraftItemDeferred,
  validateDraftItems,
  type DraftItemKind,
  type PlanningContextDecisionAction,
  type PlanningContextItem,
  type PlanningContextResponse,
  type PlanningDraftItem,
  type PlanningFeasibility,
  type PlanningQuestion,
  type PlanningReturnTo,
  type PlanningTargetType,
} from "@/src/lib/planning";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

const DECISIONS: {
  action: PlanningContextDecisionAction;
  label: string;
}[] = [
  { action: "looks_right", label: "Looks right" },
  { action: "change", label: "Change" },
  { action: "dont_know", label: "I don’t know yet" },
  { action: "not_right", label: "That’s not right" },
];

export default function PlanningContextReviewScreen() {
  const params = useLocalSearchParams<{
    targetType?: string;
    targetId?: string;
  }>();
  const router = useRouter();
  const targetType = isPlanningTargetType(params.targetType)
    ? params.targetType
    : null;
  const targetId =
    typeof params.targetId === "string" && params.targetId.trim()
      ? params.targetId
      : null;

  const [proposal, setProposal] = useState<PlanningContextResponse | null>(null);
  const [draftItems, setDraftItems] = useState<PlanningDraftItem[]>([]);
  const [draftDirty, setDraftDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingApply, setConfirmingApply] = useState(false);

  const acceptProposal = useCallback((next: PlanningContextResponse) => {
    setProposal(next);
    setDraftItems(next.draft_plan.items);
    setDraftDirty(false);
    setError(null);
  }, []);

  const load = useCallback(async () => {
    if (!targetType || !targetId) {
      setError("This planning link is incomplete. Return to the goal or project and try again.");
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const next = await api.planningCreateContextReview({
        target_type: targetType,
        target_id: targetId,
      });
      acceptProposal(next);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "Hymn could not read this plan. Please try again."));
    } finally {
      setLoading(false);
    }
  }, [acceptProposal, targetId, targetType]);

  useEffect(() => {
    void load();
  }, [load]);

  const decideContextItem = async (
    item: PlanningContextItem,
    action: PlanningContextDecisionAction,
    value?: string,
  ) => {
    if (!proposal) return;
    try {
      setBusy(`context:${item.key}`);
      const next = await api.planningDecideContextItem(
        proposal.id,
        item.key,
        action,
        value,
      );
      acceptProposal(next);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That change was not saved. Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const answerQuestion = async (question: PlanningQuestion, value: string) => {
    if (!proposal) return;
    try {
      setBusy(`question:${question.id}`);
      const next = await api.planningAnswerQuestion(
        proposal.id,
        question.id,
        value,
      );
      acceptProposal(next);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That answer was not saved. Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const prepareDraft = async () => {
    if (!proposal) return;
    try {
      setBusy("draft");
      const next = await api.planningGenerateDraft(proposal.id);
      acceptProposal(next);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "Hymn could not prepare the draft. Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const changeDraftItems = (next: PlanningDraftItem[]) => {
    setDraftItems(next);
    setDraftDirty(true);
    setConfirmingApply(false);
  };

  const addDraftItem = (kind: DraftItemKind) => {
    const id = `new-${Date.now()}-${draftItems.length}`;
    changeDraftItems([
      ...draftItems,
      createDraftItem(kind, id, draftItems.length),
    ]);
  };

  const saveDraft = async () => {
    if (!proposal) return;
    const validation = validateDraftItems(draftItems);
    if (validation) {
      setError(validation);
      return;
    }
    try {
      setBusy("save-draft");
      const next = await api.planningSaveDraft(proposal.id, draftItems);
      acceptProposal(next);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "The draft was not saved. Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const navigateToReturn = (returnTo: PlanningReturnTo) => {
    const id = encodeURIComponent(returnTo.target_id);
    if (returnTo.target_type === "goal") {
      router.replace(`/goals/${id}`);
    } else if (returnTo.target_type === "project") {
      router.replace(`/projects/${id}`);
    } else {
      router.replace(`/knowledge/${id}`);
    }
  };

  const applyDraft = async () => {
    if (!proposal) return;
    try {
      setBusy("apply");
      const result = await api.planningApply(proposal.id);
      navigateToReturn(result.return_to);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "The plan was not applied. Nothing new was created."));
      setConfirmingApply(false);
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <Page>
        <CenteredState
          icon={<ActivityIndicator color={colors.brandPrimary} />}
          title="Understanding your situation…"
          body="Hymn is reading only the records linked to this goal or project."
        />
      </Page>
    );
  }

  if (!proposal) {
    return (
      <Page>
        <CenteredState
          icon={<Ionicons name="alert-circle-outline" size={30} color={colors.error} />}
          title="This plan could not be opened"
          body={error ?? "No planning details were returned."}
          actionLabel="Try again"
          onAction={() => void load()}
        />
      </Page>
    );
  }

  const sections = orderedContextSections(proposal.context_review.sections);
  const hasQuestions = proposal.context_review.questions.length > 0;
  const draftValidation = validateDraftItems(draftItems);
  const canApply =
    proposal.draft_plan.can_apply &&
    !draftDirty &&
    !draftValidation &&
    !hasQuestions &&
    proposal.stage !== "applied";

  return (
    <Page>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.hero}>
          <Text style={styles.eyebrow}>
            {targetTypeLabel(proposal.target_type)} planning
          </Text>
          <Text style={styles.pageTitle}>Does Hymn understand your situation?</Text>
          <Text style={styles.intro}>{proposal.context_review.intro}</Text>
          <View style={styles.nextAction}>
            <Ionicons name="navigate-circle-outline" size={20} color={colors.brandPrimary} />
            <Text style={styles.nextActionText}>{nextActionSummary(proposal)}</Text>
          </View>
        </View>

        {error ? (
          <View style={styles.errorBanner}>
            <Text style={styles.errorBannerText}>{error}</Text>
            <Pressable onPress={() => setError(null)} hitSlop={8}>
              <Text style={styles.errorDismiss}>Dismiss</Text>
            </Pressable>
          </View>
        ) : null}

        {sections.map((section) => (
          <Section key={section.key} title={section.title}>
            {section.items.length > 0 ? (
              section.items.map((item) => (
                <ContextItemCard
                  key={item.key}
                  item={item}
                  busy={busy === `context:${item.key}`}
                  disabled={busy !== null || proposal.stage === "applied"}
                  readonly={proposal.stage === "applied"}
                  onDecide={(action, value) =>
                    void decideContextItem(item, action, value)
                  }
                />
              ))
            ) : (
              <Text style={styles.emptyText}>
                {section.key === "what_hymn_still_needs" && !hasQuestions
                  ? "Hymn has enough context to prepare a draft."
                  : "Nothing relevant is recorded here yet."}
              </Text>
            )}
          </Section>
        ))}

        {hasQuestions ? (
          <Section title="A few things to clarify">
            <Text style={styles.sectionIntro}>
              These answers are needed before Hymn can prepare an honest plan.
            </Text>
            {proposal.context_review.questions.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                busy={busy === `question:${question.id}`}
                disabled={busy !== null}
                onSave={(value) => void answerQuestion(question, value)}
              />
            ))}
          </Section>
        ) : null}

        <FeasibilityCard feasibility={proposal.context_review.feasibility} />

        <Section title="Your draft plan">
          {draftItems.length > 0 ? (
            <>
              <Text style={styles.sectionIntro}>
                Nothing below is created until you approve it. Edit, reorder,
                defer, or remove anything first.
              </Text>
              {draftItems.map((item, index) => (
                <DraftItemEditor
                  key={item.id}
                  item={item}
                  first={index === 0}
                  last={index === draftItems.length - 1}
                  disabled={busy !== null || proposal.stage === "applied"}
                  onChange={(next) =>
                    changeDraftItems(replaceDraftItem(draftItems, next))
                  }
                  onMove={(direction) =>
                    changeDraftItems(moveDraftItem(draftItems, item.id, direction))
                  }
                  onToggleDeferred={() =>
                    changeDraftItems(toggleDraftItemDeferred(draftItems, item.id))
                  }
                  onRemove={() =>
                    changeDraftItems(removeDraftItem(draftItems, item.id))
                  }
                />
              ))}
            </>
          ) : (
            <Text style={styles.emptyText}>{planningEmptyState(proposal.stage)}</Text>
          )}

          {proposal.stage !== "applied" && proposal.draft_plan.version > 0 ? (
            <View style={styles.addRow}>
              {(["milestone", "outcome", "task"] as const).map((kind) => (
                <Pressable
                  key={kind}
                  onPress={() => addDraftItem(kind)}
                  disabled={busy !== null || proposal.stage === "applied"}
                  style={styles.smallButton}
                >
                  <Ionicons name="add" size={16} color={colors.onSurface} />
                  <Text style={styles.smallButtonText}>Add {kind}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}

          {draftDirty ? (
            <View style={styles.unsavedBox}>
              <Text style={styles.unsavedText}>You have unsaved plan changes.</Text>
              {draftValidation ? (
                <Text style={styles.validationText}>{draftValidation}</Text>
              ) : null}
              <Pressable
                style={[
                  styles.primaryButton,
                  (busy !== null || Boolean(draftValidation)) && styles.disabled,
                ]}
                disabled={busy !== null || Boolean(draftValidation)}
                onPress={() => void saveDraft()}
              >
                {busy === "save-draft" ? (
                  <ActivityIndicator color={colors.onBrandPrimary} />
                ) : (
                  <Text style={styles.primaryButtonText}>Save plan changes</Text>
                )}
              </Pressable>
            </View>
          ) : null}

          {!hasQuestions &&
          proposal.stage !== "applied" &&
          draftItems.length === 0 &&
          !draftDirty ? (
            <Pressable
              style={[styles.primaryButton, busy !== null && styles.disabled]}
              disabled={busy !== null}
              onPress={() => void prepareDraft()}
            >
              {busy === "draft" ? (
                <ActivityIndicator color={colors.onBrandPrimary} />
              ) : (
                <Text style={styles.primaryButtonText}>Prepare a draft plan</Text>
              )}
            </Pressable>
          ) : null}
        </Section>

        {proposal.stage === "applied" ? (
          <View style={styles.completionCard}>
            <Ionicons name="checkmark-circle" size={28} color={colors.success} />
            <View style={styles.flex}>
              <Text style={styles.completionTitle}>Plan attached</Text>
              <Text style={styles.itemHelp}>
                The approved plan is now visible on the original{" "}
                {proposal.return_to.target_type}.
              </Text>
            </View>
            <Pressable
              style={styles.secondaryButton}
              onPress={() => navigateToReturn(proposal.return_to)}
            >
              <Text style={styles.secondaryButtonText}>{proposal.return_to.label}</Text>
            </Pressable>
          </View>
        ) : draftItems.length > 0 ? (
          <View style={styles.approvalCard}>
            <Text style={styles.sectionTitle}>Ready to add this plan?</Text>
            <Text style={styles.sectionIntro}>
              Hymn will create only the active items shown above and attach them
              to this {proposal.target_type}. Repeating this action will not
              create duplicates.
            </Text>
            {confirmingApply ? (
              <View style={styles.confirmBox}>
                <Text style={styles.confirmTitle}>Apply this exact draft?</Text>
                <Text style={styles.itemHelp}>
                  Deferred items remain in the draft and are not created now.
                </Text>
                <View style={styles.buttonRow}>
                  <Pressable
                    style={styles.secondaryButton}
                    disabled={busy !== null}
                    onPress={() => setConfirmingApply(false)}
                  >
                    <Text style={styles.secondaryButtonText}>Keep reviewing</Text>
                  </Pressable>
                  <Pressable
                    style={[
                      styles.primaryButton,
                      (!canApply || busy !== null) && styles.disabled,
                      styles.flex,
                    ]}
                    disabled={!canApply || busy !== null}
                    onPress={() => void applyDraft()}
                  >
                    {busy === "apply" ? (
                      <ActivityIndicator color={colors.onBrandPrimary} />
                    ) : (
                      <Text style={styles.primaryButtonText}>Yes, apply plan</Text>
                    )}
                  </Pressable>
                </View>
              </View>
            ) : (
              <>
                <Pressable
                  style={[styles.primaryButton, !canApply && styles.disabled]}
                  disabled={!canApply}
                  onPress={() => setConfirmingApply(true)}
                >
                  <Text style={styles.primaryButtonText}>Review and apply</Text>
                </Pressable>
                {!canApply ? (
                  <Text style={styles.validationText}>
                    {draftDirty
                      ? "Save your plan changes before applying."
                      : hasQuestions
                        ? "Answer the questions above before applying."
                        : draftValidation ??
                          "Hymn needs more context before this plan can be applied."}
                  </Text>
                ) : null}
              </>
            )}
          </View>
        ) : null}
      </ScrollView>
    </Page>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Plan with Hymn" }} />
      {children}
    </SafeAreaView>
  );
}

function CenteredState({
  icon,
  title,
  body,
  actionLabel,
  onAction,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.center}>
      {icon}
      <Text style={styles.centerTitle}>{title}</Text>
      <Text style={styles.centerBody}>{body}</Text>
      {actionLabel && onAction ? (
        <Pressable style={styles.primaryButton} onPress={onAction}>
          <Text style={styles.primaryButtonText}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

function ContextItemCard({
  item,
  busy,
  disabled,
  readonly,
  onDecide,
}: {
  item: PlanningContextItem;
  busy: boolean;
  disabled: boolean;
  readonly: boolean;
  onDecide: (action: PlanningContextDecisionAction, value?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(item.value ?? "");
  const [showWhy, setShowWhy] = useState(false);

  useEffect(() => {
    setEditValue(item.value ?? "");
    setEditing(false);
  }, [item.value]);

  const canEdit = item.editable && item.editor !== "account_select";
  const valueLabel =
    item.status === "missing" || !item.value ? "Not known yet" : item.value;

  return (
    <View style={styles.contextItem}>
      <View style={styles.itemHeader}>
        <View style={styles.flex}>
          <Text style={styles.itemLabel}>{item.label}</Text>
          <Text style={item.status === "missing" ? styles.missingValue : styles.itemValue}>
            {valueLabel}
          </Text>
        </View>
        <Text style={styles.sourceBadge}>
          {item.status === "user_edited"
            ? "Your correction"
            : item.status === "missing"
              ? "Needs context"
              : "From Hymn"}
        </Text>
      </View>

      {editing ? (
        <View style={styles.editorBox}>
          <TextInput
            value={editValue}
            onChangeText={setEditValue}
            placeholder={editorPlaceholder(item)}
            placeholderTextColor={colors.onSurfaceTertiary}
            keyboardType={item.editor === "money" ? "decimal-pad" : "default"}
            autoCapitalize={item.editor === "text" ? "sentences" : "none"}
            style={styles.input}
            multiline={item.editor === "text"}
            autoFocus
          />
          <View style={styles.buttonRow}>
            <Pressable
              style={styles.secondaryButton}
              disabled={disabled}
              onPress={() => {
                setEditValue(item.value ?? "");
                setEditing(false);
              }}
            >
              <Text style={styles.secondaryButtonText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[
                styles.primaryButton,
                (!editValue.trim() || disabled) && styles.disabled,
                styles.flex,
              ]}
              disabled={!editValue.trim() || disabled}
              onPress={() => {
                setEditing(false);
                onDecide("change", editValue.trim());
              }}
            >
              {busy ? (
                <ActivityIndicator color={colors.onBrandPrimary} />
              ) : (
                <Text style={styles.primaryButtonText}>Save change</Text>
              )}
            </Pressable>
          </View>
        </View>
      ) : item.editable && !readonly ? (
        <View style={styles.decisionRow}>
          {DECISIONS.map((decision) =>
            decision.action === "change" && !canEdit ? null : (
              <Pressable
                key={decision.action}
                style={styles.decisionButton}
                disabled={disabled}
                onPress={() => {
                  if (decision.action === "change") {
                    setEditing(true);
                  } else {
                    onDecide(decision.action);
                  }
                }}
              >
                <Text style={styles.decisionButtonText}>{decision.label}</Text>
              </Pressable>
            ),
          )}
        </View>
      ) : null}

      <Pressable
        style={styles.disclosureButton}
        onPress={() => setShowWhy((current) => !current)}
      >
        <Text style={styles.disclosureText}>Why does Hymn think this?</Text>
        <Ionicons
          name={showWhy ? "chevron-up" : "chevron-down"}
          size={16}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>
      {showWhy ? (
        <View style={styles.evidenceBox}>
          <Text style={styles.itemHelp}>{item.why.summary}</Text>
          {item.why.evidence.map((evidence) => (
            <Text key={evidence} style={styles.evidenceLine}>
              • {evidence}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function QuestionCard({
  question,
  busy,
  disabled,
  onSave,
}: {
  question: PlanningQuestion;
  busy: boolean;
  disabled: boolean;
  onSave: (value: string) => void;
}) {
  const [value, setValue] = useState("");

  return (
    <View style={styles.questionCard}>
      <Text style={styles.questionTitle}>{question.prompt}</Text>
      <Text style={styles.itemHelp}>{question.help_text}</Text>
      {question.input_type === "select" ? (
        <View style={styles.optionList}>
          {question.options.map((option) => (
            <Pressable
              key={option.value}
              style={[
                styles.optionButton,
                value === option.value && styles.optionButtonSelected,
              ]}
              disabled={disabled}
              onPress={() => setValue(option.value)}
            >
              <Ionicons
                name={value === option.value ? "radio-button-on" : "radio-button-off"}
                size={18}
                color={
                  value === option.value
                    ? colors.brandPrimary
                    : colors.onSurfaceSecondary
                }
              />
              <Text style={styles.optionText}>{option.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : (
        <TextInput
          value={value}
          onChangeText={setValue}
          placeholder={
            question.input_type === "date"
              ? "YYYY-MM-DD"
              : question.input_type === "money"
                ? "Enter an amount"
                : "Type your answer"
          }
          placeholderTextColor={colors.onSurfaceTertiary}
          keyboardType={question.input_type === "money" ? "decimal-pad" : "default"}
          style={styles.input}
          multiline={question.input_type === "text"}
        />
      )}
      <Pressable
        style={[
          styles.primaryButton,
          (disabled || (question.required && !value.trim())) && styles.disabled,
        ]}
        disabled={disabled || (question.required && !value.trim())}
        onPress={() => onSave(value.trim())}
      >
        {busy ? (
          <ActivityIndicator color={colors.onBrandPrimary} />
        ) : (
          <Text style={styles.primaryButtonText}>Save answer</Text>
        )}
      </Pressable>
      <Pressable
        style={[styles.secondaryButton, disabled && styles.disabled]}
        disabled={disabled}
        onPress={() => onSave("")}
      >
        <Text style={styles.secondaryButtonText}>I don&apos;t know yet</Text>
      </Pressable>
    </View>
  );
}

function FeasibilityCard({ feasibility }: { feasibility: PlanningFeasibility }) {
  const statusCopy = {
    appears_feasible: "Appears feasible",
    may_be_difficult: "May be difficult",
    insufficient_information: "Not enough information yet",
  }[feasibility.status];

  return (
    <Section title="What looks realistic">
      <View style={styles.feasibilityHeader}>
        <Text style={styles.feasibilityStatus}>{statusCopy}</Text>
        <Text style={styles.sectionIntro}>{feasibility.summary}</Text>
      </View>
      <ReadableList title="What appears feasible" items={feasibility.appears_feasible} />
      <ReadableList title="What may make it difficult" items={feasibility.difficulties} />
      {feasibility.calculations.length > 0 ? (
        <View style={styles.readableGroup}>
          <Text style={styles.groupTitle}>Calculations Hymn used</Text>
          {feasibility.calculations.map((calculation) => (
            <View key={`${calculation.label}:${calculation.value}`} style={styles.calculation}>
              <Text style={styles.itemLabel}>{calculation.label}</Text>
              <Text style={styles.itemValue}>{calculation.value}</Text>
              <Text style={styles.itemHelp}>{calculation.explanation}</Text>
            </View>
          ))}
        </View>
      ) : null}
      <ReadableList title="What cannot yet be determined" items={feasibility.unknowns} />
    </Section>
  );
}

function ReadableList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <View style={styles.readableGroup}>
      <Text style={styles.groupTitle}>{title}</Text>
      {items.map((item) => (
        <Text key={item} style={styles.listItem}>
          • {item}
        </Text>
      ))}
    </View>
  );
}

function DraftItemEditor({
  item,
  first,
  last,
  disabled,
  onChange,
  onMove,
  onToggleDeferred,
  onRemove,
}: {
  item: PlanningDraftItem;
  first: boolean;
  last: boolean;
  disabled: boolean;
  onChange: (next: PlanningDraftItem) => void;
  onMove: (direction: "up" | "down") => void;
  onToggleDeferred: () => void;
  onRemove: () => void;
}) {
  return (
    <View style={[styles.draftItem, item.status === "deferred" && styles.deferredItem]}>
      <View style={styles.itemHeader}>
        <Text style={styles.kindBadge}>{draftKindLabel(item.kind)}</Text>
        <View style={styles.orderButtons}>
          <Pressable
            style={[styles.iconButton, first && styles.disabled]}
            disabled={first || disabled}
            onPress={() => onMove("up")}
            accessibilityLabel={`Move ${item.title || item.kind} up`}
          >
            <Ionicons name="arrow-up" size={17} color={colors.onSurfaceSecondary} />
          </Pressable>
          <Pressable
            style={[styles.iconButton, last && styles.disabled]}
            disabled={last || disabled}
            onPress={() => onMove("down")}
            accessibilityLabel={`Move ${item.title || item.kind} down`}
          >
            <Ionicons name="arrow-down" size={17} color={colors.onSurfaceSecondary} />
          </Pressable>
        </View>
      </View>
      <Text style={styles.inputLabel}>Title</Text>
      <TextInput
        value={item.title}
        onChangeText={(title) => onChange({ ...item, title })}
        placeholder={`Describe this ${item.kind}`}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
        editable={!disabled}
      />
      <Text style={styles.inputLabel}>Helpful detail</Text>
      <TextInput
        value={item.notes}
        onChangeText={(notes) => onChange({ ...item, notes })}
        placeholder="What should be true when this is done?"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={[styles.input, styles.notesInput]}
        multiline
        editable={!disabled}
      />
      <View style={styles.decisionRow}>
        <Pressable
          style={styles.decisionButton}
          disabled={disabled}
          onPress={onToggleDeferred}
        >
          <Text style={styles.decisionButtonText}>
            {item.status === "deferred" ? "Include now" : "Defer"}
          </Text>
        </Pressable>
        <Pressable
          style={styles.decisionButton}
          disabled={disabled}
          onPress={onRemove}
        >
          <Text style={[styles.decisionButtonText, styles.removeText]}>Remove</Text>
        </Pressable>
      </View>
    </View>
  );
}

function targetTypeLabel(targetType: PlanningTargetType): string {
  if (targetType === "goal") return "Goal";
  if (targetType === "project") return "Project";
  return "Learning journey";
}

function draftKindLabel(kind: DraftItemKind): string {
  if (kind === "milestone") return "Milestone";
  if (kind === "outcome") return "Expected outcome";
  return "Task";
}

function editorPlaceholder(item: PlanningContextItem): string {
  if (item.editor === "date") return "YYYY-MM-DD";
  if (item.editor === "money") return "Enter an amount";
  return `Enter ${item.label.toLowerCase()}`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxxl },
  flex: { flex: 1 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  centerTitle: {
    marginTop: spacing.md,
    fontFamily: fonts.displayBold,
    fontSize: 20,
    color: colors.onSurface,
    textAlign: "center",
  },
  centerBody: {
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
    fontFamily: fonts.body,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    lineHeight: 20,
  },
  hero: { marginBottom: spacing.xl },
  eyebrow: {
    fontFamily: fonts.body,
    color: colors.brandPrimary,
    fontSize: 12,
    letterSpacing: 1,
    textTransform: "uppercase",
    marginBottom: spacing.xs,
  },
  pageTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 27,
    lineHeight: 34,
    color: colors.onSurface,
  },
  intro: {
    fontFamily: fonts.body,
    fontSize: 15,
    lineHeight: 22,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.sm,
  },
  nextAction: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.brandTertiary,
    padding: spacing.md,
    borderRadius: radius.md,
  },
  nextActionText: {
    flex: 1,
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.onBrandTertiary,
  },
  section: { marginBottom: spacing.lg },
  sectionTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 17,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  sectionIntro: {
    fontFamily: fonts.body,
    fontSize: 13,
    lineHeight: 19,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.md,
  },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  contextItem: {
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  itemHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  itemLabel: {
    fontFamily: fonts.displayBold,
    fontSize: 14,
    color: colors.onSurface,
  },
  itemValue: {
    fontFamily: fonts.body,
    fontSize: 14,
    lineHeight: 20,
    color: colors.onSurfaceSecondary,
    marginTop: 3,
  },
  missingValue: {
    fontFamily: fonts.body,
    fontSize: 14,
    color: colors.warning,
    marginTop: 3,
  },
  sourceBadge: {
    fontFamily: fonts.body,
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    backgroundColor: colors.surfaceTertiary,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
  },
  decisionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  decisionButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 7,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
  },
  decisionButtonText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.onSurface,
  },
  disclosureButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    marginTop: spacing.md,
    alignSelf: "flex-start",
  },
  disclosureText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.onSurfaceSecondary,
  },
  evidenceBox: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
  },
  evidenceLine: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 18,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.xs,
  },
  itemHelp: {
    fontFamily: fonts.body,
    fontSize: 12,
    lineHeight: 18,
    color: colors.onSurfaceSecondary,
  },
  editorBox: { marginTop: spacing.md },
  inputLabel: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  input: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
    color: colors.onSurface,
    fontFamily: fonts.body,
    fontSize: 14,
  },
  notesInput: { minHeight: 70, textAlignVertical: "top" },
  buttonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  primaryButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  primaryButtonText: {
    color: colors.onBrandPrimary,
    fontFamily: fonts.displayBold,
    fontSize: 14,
  },
  secondaryButton: {
    minHeight: 42,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
  },
  secondaryButtonText: {
    color: colors.onSurface,
    fontFamily: fonts.body,
    fontSize: 13,
  },
  disabled: { opacity: 0.45 },
  questionCard: {
    marginTop: spacing.sm,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  questionTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: colors.onSurface,
    marginBottom: spacing.xs,
  },
  optionList: { gap: spacing.sm, marginVertical: spacing.md },
  optionButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  optionButtonSelected: {
    backgroundColor: colors.brandTertiary,
    borderColor: colors.brandPrimary,
  },
  optionText: {
    flex: 1,
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.onSurface,
  },
  feasibilityHeader: { marginBottom: spacing.md },
  feasibilityStatus: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: colors.onSurface,
    marginBottom: spacing.xs,
  },
  readableGroup: {
    paddingTop: spacing.md,
    marginTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  groupTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 13,
    color: colors.onSurface,
    marginBottom: spacing.xs,
  },
  listItem: {
    fontFamily: fonts.body,
    fontSize: 13,
    lineHeight: 19,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.xs,
  },
  calculation: { marginTop: spacing.sm },
  draftItem: {
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  deferredItem: { opacity: 0.65 },
  kindBadge: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.brandPrimary,
    textTransform: "uppercase",
    letterSpacing: 0.7,
    flex: 1,
  },
  orderButtons: { flexDirection: "row", gap: spacing.xs },
  iconButton: {
    width: 32,
    height: 32,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  removeText: { color: colors.error },
  addRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  smallButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  smallButtonText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.onSurface,
  },
  unsavedBox: {
    marginTop: spacing.md,
    padding: spacing.md,
    backgroundColor: "#F5E6C7",
    borderRadius: radius.md,
  },
  unsavedText: {
    fontFamily: fonts.displayBold,
    fontSize: 13,
    color: "#7A5C1C",
    marginBottom: spacing.sm,
  },
  validationText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.error,
    textAlign: "center",
    marginTop: spacing.sm,
  },
  approvalCard: {
    backgroundColor: colors.brandTertiary,
    padding: spacing.lg,
    borderRadius: radius.lg,
    marginBottom: spacing.xl,
  },
  confirmBox: { marginTop: spacing.sm },
  confirmTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 14,
    color: colors.onSurface,
  },
  completionCard: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.md,
    backgroundColor: colors.brandTertiary,
    padding: spacing.lg,
    borderRadius: radius.lg,
    marginBottom: spacing.xl,
  },
  completionTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: colors.onBrandTertiary,
  },
  emptyText: {
    fontFamily: fonts.body,
    fontSize: 13,
    lineHeight: 19,
    color: colors.onSurfaceSecondary,
  },
  errorBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: "#F4D1CB",
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.lg,
  },
  errorBannerText: {
    flex: 1,
    fontFamily: fonts.body,
    fontSize: 13,
    color: "#7A2B1E",
  },
  errorDismiss: {
    fontFamily: fonts.displayBold,
    fontSize: 12,
    color: "#7A2B1E",
  },
});
