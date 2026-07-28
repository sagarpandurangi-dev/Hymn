import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  ActivityIndicator,
  Animated,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, type ApiError } from "@/src/lib/api";
import {
  canPlaceNode,
  dreamApplyReadiness,
  dreamDecisionCounts,
  factByKey,
  journeyChipLabel,
  localReferenceDate,
  nodeDepth,
  purchaseConversationSummary,
  researchActionLabel,
  siblingMoveOperation,
  suggestedAddKind,
  visiblePlanNodes,
  type DreamClarificationQuestion,
  type DreamNode,
  type DreamNodeKind,
  type DreamProposal,
  type DreamSourceType,
  type DreamTreeOperation,
  type JourneyShape,
  type JourneyShapeOption,
  type PlanningDepth,
} from "@/src/lib/dreams";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Props = {
  proposalId?: string;
  sourceType?: DreamSourceType;
  sourceId?: string;
  initialShape?: JourneyShape;
};

const NODE_LABELS: Record<DreamNodeKind, string> = {
  phase: "Phase",
  milestone: "Milestone",
  task: "Task",
  checkin_requirement: "Required check-in",
};

const DEPTH_LABELS: Record<PlanningDepth, string> = {
  light: "Light",
  moderate: "Moderate",
  major: "Major",
  transformational: "Transformational",
};

const errorMessage = (error: unknown, fallback: string): string =>
  (error as ApiError | undefined)?.message || fallback;

const creationEffectCopy = (proposal: DreamProposal): string => {
  switch (proposal.source.type) {
    case "goal":
      return "Attach this plan to your existing goal";
    case "project":
      return "Attach this plan to your existing project";
    case "journey":
      return "Attach this plan to your existing learning journey";
    case "learning":
      return "Create a learning journey with this plan attached";
    default:
      return "Save one active plan for this intention";
  }
};

function Section({
  title,
  children,
  testID,
}: {
  title: string;
  children: React.ReactNode;
  testID?: string;
}) {
  return (
    <View style={styles.section} testID={testID}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Pill({
  label,
  selected = false,
  onPress,
  disabled = false,
  testID,
}: {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  disabled?: boolean;
  testID?: string;
}) {
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : "text"}
      disabled={disabled || !onPress}
      onPress={onPress}
      style={[styles.pill, selected && styles.pillSelected, disabled && styles.disabled]}
      testID={testID}
    >
      <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function Disclosure({
  title,
  lines,
}: {
  title: string;
  lines: string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.disclosure}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((value) => !value)}
        style={styles.disclosureButton}
      >
        <Text style={styles.disclosureTitle}>{title}</Text>
        <Ionicons
          name={open ? "chevron-up" : "chevron-down"}
          size={17}
          color={colors.onSurfaceSecondary}
        />
      </Pressable>
      {open ? (
        <View style={styles.disclosureBody}>
          {lines.length ? lines.map((line, index) => (
            <Text key={`${line}-${index}`} style={styles.muted}>• {line}</Text>
          )) : <Text style={styles.muted}>No additional evidence is recorded.</Text>}
        </View>
      ) : null}
    </View>
  );
}

function ShapePicker({
  shapes,
  selected,
  onSelect,
  disabled,
  opacity,
}: {
  shapes: JourneyShapeOption[];
  selected?: JourneyShape;
  onSelect: (shape: JourneyShape) => void;
  disabled: boolean;
  opacity: Animated.Value;
}) {
  return (
    <Animated.View style={{ opacity }} testID="dream-shape-picker">
      <Text style={styles.label}>Shape this journey</Text>
      <Text style={styles.helper}>
        Suggestions are lenses, not restrictions. You can always choose Custom.
      </Text>
      <View style={styles.shapeGrid}>
        {shapes.map((shape) => (
          <Pressable
            key={shape.id}
            accessibilityRole="button"
            accessibilityState={{ selected: selected === shape.id }}
            disabled={disabled}
            onPress={() => onSelect(shape.id)}
            style={[
              styles.shapeTile,
              selected === shape.id && styles.shapeTileSelected,
            ]}
            testID={`dream-shape-${shape.id}`}
          >
            <Text style={styles.shapeTitle}>{shape.label}</Text>
            <Text style={styles.shapeDescription}>{shape.description}</Text>
          </Pressable>
        ))}
      </View>
    </Animated.View>
  );
}

function ClarificationCard({
  question,
  proposal,
  busy,
  onSave,
  onNotSure,
}: {
  question: DreamClarificationQuestion;
  proposal: DreamProposal;
  busy: boolean;
  onSave: (corrections: Record<string, unknown>) => Promise<void>;
  onNotSure: (keys: string[]) => Promise<void>;
}) {
  const amountFact = factByKey(proposal, "amount");
  const currencyFact = factByKey(proposal, "currency");
  const deadlineFact = factByKey(proposal, "deadline");
  const [editing, setEditing] = useState(question.status === "missing");
  const [amount, setAmount] = useState(
    amountFact?.value ? String(amountFact.value) : "",
  );
  const [currency, setCurrency] = useState(
    currencyFact?.value
      ? String(currencyFact.value)
      : proposal.context.finance.profile_currency || "",
  );
  const [deadline, setDeadline] = useState(
    deadlineFact?.value ? String(deadlineFact.value) : "",
  );
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setAmount(amountFact?.value ? String(amountFact.value) : "");
    setCurrency(
      currencyFact?.value
        ? String(currencyFact.value)
        : proposal.context.finance.profile_currency || "",
    );
    setDeadline(deadlineFact?.value ? String(deadlineFact.value) : "");
  }, [
    amountFact?.value,
    currencyFact?.value,
    deadlineFact?.value,
    proposal.context.finance.profile_currency,
  ]);

  const valid = question.kind === "money"
    ? Number(amount.replaceAll(",", "")) > 0 && /^[A-Za-z]{3}$/.test(currency.trim())
    : question.kind === "date"
      ? /^\d{4}-\d{2}-\d{2}$/.test(deadline)
      : false;

  const answerLabel = question.kind === "money"
    ? amountFact?.value && currencyFact?.value
      ? `${String(currencyFact.value).toUpperCase()} ${String(amountFact.value)}`
      : "Not answered yet"
    : deadlineFact?.value
      ? String(deadlineFact.value)
      : "Not answered yet";

  return (
    <View
      accessibilityLabel={question.prompt}
      style={[
        styles.questionCard,
        question.status === "answered" && styles.questionCardAnswered,
      ]}
      testID={`dream-question-${question.id}`}
    >
      <Text style={styles.questionTitle}>{question.prompt}</Text>
      {question.status === "unknown" && !editing ? (
        <Text style={styles.questionAnswer}>You’re not sure yet. That’s okay—the map will stay provisional.</Text>
      ) : question.status === "answered" && !editing ? (
        <Text style={styles.questionAnswer}>{answerLabel}</Text>
      ) : null}

      {editing ? (
        <View style={styles.questionInputs}>
          {question.kind === "money" ? (
            <View style={styles.moneyInputs}>
              <TextInput
                accessibilityLabel="Expected price"
                editable={!busy}
                inputMode="decimal"
                onChangeText={(value) => {
                  setAmount(value);
                  setSaved(false);
                }}
                placeholder="Price or range"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[styles.input, { flex: 1 }]}
                value={amount}
              />
              <TextInput
                accessibilityLabel="Currency"
                autoCapitalize="characters"
                editable={!busy}
                maxLength={3}
                onChangeText={(value) => {
                  setCurrency(value.toUpperCase());
                  setSaved(false);
                }}
                placeholder="INR"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[styles.input, styles.currencyInput]}
                value={currency}
              />
            </View>
          ) : (
            <TextInput
              accessibilityLabel="Desired purchase date"
              editable={!busy}
              onChangeText={(value) => {
                setDeadline(value);
                setSaved(false);
              }}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
              value={deadline}
            />
          )}
          <View style={styles.actionRow}>
            <Pressable
              accessibilityRole="button"
              disabled={busy || !valid}
              onPress={() => {
                const corrections = question.kind === "money"
                  ? {
                      amount: amount.replaceAll(",", ""),
                      currency: currency.trim().toUpperCase(),
                    }
                  : { deadline };
                void onSave(corrections).then(() => {
                  setEditing(false);
                  setSaved(true);
                });
              }}
              style={[styles.primarySmall, (busy || !valid) && styles.disabled]}
            >
              <Text style={styles.primarySmallText}>Save answer</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              onPress={() => {
                void onNotSure(question.fact_keys).then(() => {
                  setEditing(false);
                  setSaved(true);
                });
              }}
              style={styles.secondarySmall}
            >
              <Text style={styles.secondarySmallText}>I’m not sure yet</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable
          accessibilityRole="button"
          disabled={busy}
          onPress={() => setEditing(true)}
          style={styles.textButton}
        >
          <Text style={styles.textButtonText}>
            {question.status === "answered" ? "Change answer" : "Add an answer"}
          </Text>
        </Pressable>
      )}
      {saved ? <Text style={styles.savedText}>Saved to this plan.</Text> : null}
      <Disclosure lines={[question.why]} title="Why is Hymn asking this?" />
    </View>
  );
}

function NodeEditor({
  node,
  busy,
  onSave,
  onCancel,
}: {
  node: DreamNode;
  busy: boolean;
  onSave: (patch: Partial<DreamNode>) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(node.title);
  const [description, setDescription] = useState(node.description);
  const [question, setQuestion] = useState(node.checkin?.question || "");
  const [schedule, setSchedule] = useState(node.checkin?.schedule_type || "manual");
  const [dueDate, setDueDate] = useState(node.checkin?.due_date || "");
  const [cadence, setCadence] = useState(node.checkin?.cadence || "weekly");
  return (
    <View style={styles.nodeEditor}>
      <Text style={styles.label}>Title</Text>
      <TextInput
        editable={!busy}
        onChangeText={setTitle}
        placeholder="Give this item a clear title"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
        value={title}
      />
      <Text style={styles.label}>Description</Text>
      <TextInput
        editable={!busy}
        multiline
        onChangeText={setDescription}
        placeholder="What will this mean in practice?"
        placeholderTextColor={colors.onSurfaceTertiary}
        style={[styles.input, styles.multiline]}
        value={description}
      />
      {node.kind === "checkin_requirement" ? (
        <>
          <Text style={styles.label}>When should Hymn ask?</Text>
          <View style={styles.pillRow}>
            {(["manual", "one_time", "recurring", "milestone_triggered"] as const).map((value) => (
              <Pill
                key={value}
                label={value.replaceAll("_", " ")}
                onPress={() => setSchedule(value)}
                selected={schedule === value}
              />
            ))}
          </View>
          <Text style={styles.label}>Question or evidence request</Text>
          <TextInput
            editable={!busy}
            multiline
            onChangeText={setQuestion}
            placeholder="What update or evidence should Hymn request?"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={[styles.input, styles.multiline]}
            value={question}
          />
          {schedule === "one_time" ? (
            <>
              <Text style={styles.label}>Due date</Text>
              <TextInput
                editable={!busy}
                onChangeText={setDueDate}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                value={dueDate}
              />
            </>
          ) : null}
          {schedule === "recurring" ? (
            <>
              <Text style={styles.label}>Cadence</Text>
              <View style={styles.pillRow}>
                {["daily", "weekly", "monthly"].map((value) => (
                  <Pill
                    key={value}
                    label={value}
                    onPress={() => setCadence(value)}
                    selected={cadence === value}
                  />
                ))}
              </View>
            </>
          ) : null}
        </>
      ) : null}
      <View style={styles.actionRow}>
        <Pressable
          disabled={busy || !title.trim() || (node.kind === "checkin_requirement" && !question.trim())}
          onPress={() => {
            const patch: Partial<DreamNode> = { title: title.trim(), description: description.trim() };
            if (node.kind === "checkin_requirement") {
              patch.checkin = {
                ...node.checkin,
                schedule_type: schedule,
                question: question.trim(),
                evidence_type: node.checkin?.evidence_type || "note",
                due_date: schedule === "one_time" ? dueDate : null,
                cadence: schedule === "recurring" ? cadence : null,
              };
            }
            void onSave(patch);
          }}
          style={[styles.primarySmall, (!title.trim() || busy) && styles.disabled]}
        >
          <Text style={styles.primarySmallText}>Save changes</Text>
        </Pressable>
        <Pressable onPress={onCancel} style={styles.secondarySmall}>
          <Text style={styles.secondarySmallText}>Cancel</Text>
        </Pressable>
      </View>
    </View>
  );
}

function AddNodeForm({
  kind,
  onAdd,
  onCancel,
  busy,
}: {
  kind: DreamNodeKind;
  onAdd: (node: Partial<DreamNode> & Pick<DreamNode, "kind" | "title">) => Promise<void>;
  onCancel: () => void;
  busy: boolean;
}) {
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  return (
    <View style={styles.addForm}>
      <Text style={styles.cardTitle}>Add {NODE_LABELS[kind].toLowerCase()}</Text>
      <TextInput
        autoFocus
        editable={!busy}
        onChangeText={setTitle}
        placeholder={`${NODE_LABELS[kind]} title`}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
        value={title}
      />
      {kind === "checkin_requirement" ? (
        <TextInput
          editable={!busy}
          multiline
          onChangeText={setQuestion}
          placeholder="What should Hymn ask for?"
          placeholderTextColor={colors.onSurfaceTertiary}
          style={[styles.input, styles.multiline]}
          value={question}
        />
      ) : null}
      <View style={styles.actionRow}>
        <Pressable
          disabled={busy || !title.trim() || (kind === "checkin_requirement" && !question.trim())}
          onPress={() => void onAdd({
            kind,
            title: title.trim(),
            description: "",
            origin: "user",
            decision_state: "accepted",
            dependencies: [],
            evidence_ids: [],
            assumptions: [],
            rank: 0,
            ...(kind === "checkin_requirement" ? {
              checkin: {
                schedule_type: "manual",
                question: question.trim(),
                evidence_type: "note",
              },
            } : {}),
          })}
          style={[styles.primarySmall, (!title.trim() || busy) && styles.disabled]}
        >
          <Text style={styles.primarySmallText}>Add</Text>
        </Pressable>
        <Pressable onPress={onCancel} style={styles.secondarySmall}>
          <Text style={styles.secondarySmallText}>Cancel</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function DreamMapScreen({
  proposalId,
  sourceType = "intent",
  sourceId,
  initialShape,
}: Props) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [selectedShape, setSelectedShape] = useState<JourneyShape | undefined>(initialShape);
  const [shapes, setShapes] = useState<JourneyShapeOption[]>([]);
  const [proposal, setProposal] = useState<DreamProposal | null>(null);
  const [loading, setLoading] = useState(Boolean(proposalId));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [viewMode, setViewMode] = useState<"map" | "list">("map");
  const [mapOpen, setMapOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [shapeChoicesOpen, setShapeChoicesOpen] = useState(false);
  const [applyNotice, setApplyNotice] = useState<string | null>(null);
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [movingNode, setMovingNode] = useState<string | null>(null);
  const [deletingNode, setDeletingNode] = useState<string | null>(null);
  const [adding, setAdding] = useState<{
    parentId?: string | null;
    relativeId?: string;
    placement: "after" | "inside_end";
    kind: DreamNodeKind;
  } | null>(null);
  const scrollRef = useRef<ScrollView | null>(null);
  const [mapOffset, setMapOffset] = useState(0);
  const [reviewOffset, setReviewOffset] = useState(0);
  const suggestionOpacity = useRef(new Animated.Value(1)).current;
  const analysisStarted = useRef(false);

  const acceptProposal = useCallback((next: DreamProposal) => {
    setProposal(next);
    setSelectedShape(next.interpretation.primary.journey_shape);
    setError(null);
  }, []);

  const loadShapes = useCallback(async (query: string) => {
    try {
      const response = await api.listJourneyShapes(query);
      setShapes(response.shapes);
      suggestionOpacity.setValue(reducedMotion ? 1 : 0);
      Animated.timing(suggestionOpacity, {
        toValue: 1,
        duration: reducedMotion
          ? response.reduced_motion_contract.reduced_motion_duration_ms
          : response.reduced_motion_contract.duration_ms,
        useNativeDriver: Platform.OS !== "web",
      }).start();
    } catch {
      // The composer remains usable; the backend will still classify on submit.
    }
  }, [reducedMotion, suggestionOpacity]);

  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (active) setReducedMotion(value);
    });
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReducedMotion,
    );
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    const timeout = setTimeout(() => {
      void loadShapes(text);
    }, 120);
    return () => clearTimeout(timeout);
  }, [loadShapes, text]);

  useEffect(() => {
    if (!proposalId) return;
    let active = true;
    void api.getDream(proposalId)
      .then((next) => {
        if (active) acceptProposal(next);
      })
      .catch((caught: unknown) => {
        if (active) setError(errorMessage(caught, "Hymn could not open this Dream map."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [acceptProposal, proposalId]);

  const analyze = useCallback(async () => {
    if (busy) return;
    if (!text.trim() && !sourceId) {
      setError("Tell Hymn what you want to do.");
      return;
    }
    try {
      setBusy("analyze");
      setError(null);
      const next = await api.analyzeDream({
        source_type: sourceType,
        source_id: sourceId,
        text: text.trim(),
        selected_shape: selectedShape,
        reference_date: localReferenceDate(),
      });
      acceptProposal(next);
      router.replace(`/dreams/${next.id}`);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "Hymn could not study this dream. Try again."));
    } finally {
      setBusy(null);
    }
  }, [acceptProposal, busy, router, selectedShape, sourceId, sourceType, text]);

  useEffect(() => {
    if (
      !proposalId
      && sourceId
      && ["goal", "project", "journey"].includes(sourceType)
      && !analysisStarted.current
    ) {
      analysisStarted.current = true;
      void analyze();
    }
  }, [analyze, proposalId, sourceId, sourceType]);

  useEffect(() => {
    if (!reviewOpen || reviewOffset <= 0) return;
    scrollRef.current?.scrollTo({
      y: Math.max(0, mapOffset + reviewOffset - spacing.lg),
      animated: !reducedMotion,
    });
  }, [mapOffset, reducedMotion, reviewOffset, reviewOpen]);

  useEffect(() => {
    if (!mapOpen || reviewOpen || mapOffset <= 0) return;
    scrollRef.current?.scrollTo({
      y: Math.max(0, mapOffset - spacing.lg),
      animated: !reducedMotion,
    });
  }, [mapOffset, mapOpen, reducedMotion, reviewOpen]);

  const chooseShape = async (shape: JourneyShape) => {
    setSelectedShape(shape);
    if (!proposal) return;
    try {
      setBusy("shape");
      acceptProposal(await api.correctDream(proposal.id, {
        expected_revision: proposal.revision,
        selected_shape: shape,
      }));
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That journey shape was not saved."));
    } finally {
      setBusy(null);
    }
  };

  const correctFacts = async (corrections: Record<string, unknown>) => {
    if (!proposal) return;
    try {
      setBusy("clarification");
      acceptProposal(await api.correctDream(proposal.id, {
        expected_revision: proposal.revision,
        fact_corrections: corrections,
      }));
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That answer was not saved."));
      throw caught;
    } finally {
      setBusy(null);
    }
  };

  const markNotSure = async (keys: string[]) => {
    if (!proposal) return;
    try {
      setBusy("clarification");
      acceptProposal(await api.correctDream(proposal.id, {
        expected_revision: proposal.revision,
        not_sure_fields: keys,
      }));
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That answer was not saved."));
      throw caught;
    } finally {
      setBusy(null);
    }
  };

  const chooseDepth = async (planningDepth: PlanningDepth) => {
    if (!proposal) return;
    try {
      setBusy("depth");
      acceptProposal(await api.correctDream(proposal.id, {
        expected_revision: proposal.revision,
        planning_depth: planningDepth,
      }));
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That planning depth was not saved."));
    } finally {
      setBusy(null);
    }
  };

  const operate = async (operation: DreamTreeOperation) => {
    if (!proposal) return;
    try {
      setBusy("map");
      acceptProposal(await api.editDreamMap(proposal.id, proposal.revision, operation));
      setEditingNode(null);
      setMovingNode(null);
      setAdding(null);
    } catch (caught: unknown) {
      setError(errorMessage(caught, "That map change was not saved."));
      throw caught;
    } finally {
      setBusy(null);
    }
  };

  const deleteNode = (node: DreamNode) => {
    setDeletingNode(node.id);
  };

  const openReview = () => {
    setMapOpen(true);
    setReviewOpen(true);
    setApplyNotice(null);
  };

  const apply = async () => {
    if (!proposal) return;
    const readiness = dreamApplyReadiness(proposal.map.nodes);
    if (!readiness.ready) {
      setApplyNotice(readiness.reason);
      return;
    }
    try {
      setBusy("apply");
      setError(null);
      setApplyNotice("Applying this reviewed revision…");
      const result = await api.applyDream(
        proposal.id,
        proposal.revision,
        readiness.acceptedNodeIds,
      );
      acceptProposal({
        ...proposal,
        status: "applied",
        applied_plan: result,
      });
      setApplyNotice(
        result.already_applied
          ? "This plan was already applied. No duplicate records were created."
          : "Your plan was applied once and attached successfully.",
      );
    } catch (caught: unknown) {
      try {
        const refreshed = await api.getDream(proposal.id);
        acceptProposal(refreshed);
        if (refreshed.status === "applied" && refreshed.applied_plan) {
          setApplyNotice("The plan finished applying. No duplicate retry is needed.");
        } else if (refreshed.status === "applying") {
          setApplyNotice(
            "Hymn is still finishing this plan. Refresh its status instead of applying again.",
          );
        } else {
          setError(errorMessage(caught, "The plan was not applied. Fix the issue below and retry."));
          setApplyNotice("Nothing partial was kept. Your reviewed draft is safe to retry.");
        }
      } catch {
        setError(errorMessage(caught, "Hymn could not confirm the apply status."));
        setApplyNotice(
          "Do not apply again yet. Refresh this plan to check whether it finished.",
        );
      }
    } finally {
      setBusy(null);
    }
  };

  const returnToSource = () => {
    if (!proposal?.applied_plan) return;
    const target = proposal.applied_plan.return_to;
    if (target.target_type === "goal") {
      router.replace({ pathname: "/goals/[id]", params: { id: target.target_id } });
    } else if (target.target_type === "project") {
      router.replace({ pathname: "/projects/[id]", params: { id: target.target_id } });
    } else if (target.target_type === "journey") {
      router.replace({ pathname: "/knowledge/[id]", params: { id: target.target_id } });
    } else {
      router.replace({ pathname: "/dreams/[id]", params: { id: proposal.id } });
    }
  };

  const shapeRows = shapes.length ? shapes : [];
  const nodes = proposal ? visiblePlanNodes(proposal.map.nodes) : [];
  const applyReadiness = proposal
    ? dreamApplyReadiness(proposal.map.nodes)
    : { ready: false, reason: null, acceptedNodeIds: [] };
  const decisionCounts = proposal
    ? dreamDecisionCounts(proposal.map.nodes)
    : null;
  const hasOpenQuestions = proposal
    ? proposal.interpretation.questions.some((question) => question.status !== "answered")
    : false;
  const desiredObject = proposal
    ? factByKey(proposal, "desired_object")
    : undefined;
  const moving = movingNode && proposal
    ? proposal.map.nodes.find((node) => node.id === movingNode)
    : null;
  const compatibleParents = moving && proposal
    ? [
        ...(canPlaceNode(moving.kind, null) ? [null] : []),
        ...proposal.map.nodes.filter(
          (candidate) =>
            candidate.id !== moving.id
            && canPlaceNode(moving.kind, candidate.kind)
            && !candidate.display_number.startsWith(`${moving.display_number}.`),
        ),
      ]
    : [];

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
          <Text style={styles.muted}>Opening your plan…</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.eyebrow}>Your journey</Text>
          <Text style={styles.headerTitle}>Plan what matters</Text>
        </View>
      </View>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          ref={scrollRef}
          keyboardShouldPersistTaps="handled"
        >
          {error ? (
            <View style={styles.errorCard} accessibilityRole="alert">
              <Text style={styles.errorText}>{error}</Text>
              <Pressable onPress={() => setError(null)} style={styles.textButton}>
                <Text style={styles.textButtonStrong}>Dismiss</Text>
              </Pressable>
            </View>
          ) : null}

          {!proposal ? (
            <>
              <View style={styles.hero}>
                <Text style={styles.heroTitle}>What do you want to make possible?</Text>
                <Text style={styles.body}>
                  Write naturally. Hymn will suggest a journey shape, show what it
                  understood, and wait for your approval before creating anything.
                </Text>
                <TextInput
                  accessibilityLabel="Describe your dream"
                  editable={!busy}
                  multiline
                  onChangeText={setText}
                  placeholder="For example: I want to attain my CA qualification by 2030"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  selectionColor={colors.brandPrimary}
                  style={styles.composer}
                  value={text}
                />
                <Text style={styles.counter}>{text.length}/4000</Text>
              </View>
              <ShapePicker
                disabled={Boolean(busy)}
                onSelect={setSelectedShape}
                opacity={suggestionOpacity}
                selected={selectedShape}
                shapes={shapeRows}
              />
              <Pressable
                accessibilityRole="button"
                disabled={Boolean(busy) || (!text.trim() && !sourceId)}
                onPress={() => void analyze()}
                style={[
                  styles.primary,
                  (Boolean(busy) || (!text.trim() && !sourceId)) && styles.disabled,
                ]}
                testID="dream-analyze"
              >
                {busy === "analyze" ? (
                  <ActivityIndicator color={colors.onBrandPrimary} />
                ) : (
                  <Text style={styles.primaryText}>Let Hymn study this</Text>
                )}
              </Pressable>
            </>
          ) : (
            <>
              <View style={styles.conversationHero} testID="dream-conversation-summary">
                <Text style={styles.heroTitle}>{purchaseConversationSummary(proposal)}</Text>
                <View style={styles.pillRow}>
                  <Pill
                    label={journeyChipLabel(proposal.interpretation.primary.journey_shape)}
                    selected
                  />
                  {desiredObject?.value ? <Pill label={String(desiredObject.value)} /> : null}
                </View>
                <Pressable
                  accessibilityRole="button"
                  disabled={Boolean(busy) || proposal.status === "applied"}
                  onPress={() => setShapeChoicesOpen((open) => !open)}
                  style={styles.textButton}
                >
                  <Text style={styles.textButtonText}>
                    {shapeChoicesOpen ? "Hide journey choices" : "Change journey type"}
                  </Text>
                </Pressable>
                <Disclosure
                  lines={[
                    proposal.interpretation.primary.reason,
                    ...proposal.interpretation.why.evidence,
                  ]}
                  title="How did Hymn understand this?"
                />
              </View>

              {shapeChoicesOpen ? (
                <ShapePicker
                  disabled={Boolean(busy) || proposal.status === "applied"}
                  onSelect={(shape) => {
                    void chooseShape(shape);
                    setShapeChoicesOpen(false);
                  }}
                  opacity={suggestionOpacity}
                  selected={proposal.interpretation.primary.journey_shape}
                  shapes={shapeRows}
                />
              ) : null}

              <Section title="A couple of useful questions" testID="dream-clarifications">
                <Text style={styles.sectionIntro}>
                  Answer what you know. “I’m not sure yet” is a valid answer, and you can refine it later.
                </Text>
                {proposal.interpretation.questions.map((question) => (
                  question.fact_keys.length ? (
                    <ClarificationCard
                      busy={Boolean(busy)}
                      key={question.id}
                      onNotSure={markNotSure}
                      onSave={correctFacts}
                      proposal={proposal}
                      question={question}
                    />
                  ) : (
                    <View key={question.id} style={styles.questionCard}>
                      <Text style={styles.questionTitle}>{question.prompt}</Text>
                      <Text style={styles.helper}>{question.why}</Text>
                      <Text style={styles.questionAnswer}>
                        You can keep this open and add the detail directly to the map.
                      </Text>
                    </View>
                  )
                ))}
              </Section>

              <Section title="Here’s how this fits your life right now">
                {proposal.context.finance.recorded_liquid_total
                  && proposal.context.finance.recorded_currency ? (
                    <View style={styles.contextHighlight}>
                      <Text style={styles.contextLabel}>Recorded liquid balance</Text>
                      <Text style={styles.metric}>
                        {proposal.context.finance.recorded_currency}{" "}
                        {proposal.context.finance.recorded_liquid_total}
                      </Text>
                      {!proposal.context.finance.requested_currency ? (
                        <Text style={styles.helper}>
                          This is recorded context only. Hymn will not compare it with the purchase until you confirm the purchase currency.
                        </Text>
                      ) : null}
                    </View>
                  ) : (
                    <View style={styles.notice}>
                      <Text style={styles.noticeTitle}>Money context is still limited</Text>
                      <Text style={styles.body}>
                        Hymn does not have a compatible recorded liquid balance for a reliable comparison.
                      </Text>
                    </View>
                  )}
                {proposal.context.finance.freshness_warning ? (
                  <View style={styles.warningCard}>
                    <Text style={styles.warningText}>{proposal.context.finance.freshness_warning}</Text>
                  </View>
                ) : null}
                <Text style={styles.body}>
                  Hymn found {proposal.context.commitments.other_active_goals.length} other active{" "}
                  {proposal.context.commitments.other_active_goals.length === 1 ? "goal" : "goals"},{" "}
                  {proposal.context.commitments.other_active_projects.length} active{" "}
                  {proposal.context.commitments.other_active_projects.length === 1 ? "project" : "projects"},{" "}
                  and {proposal.context.commitments.open_task_count} open{" "}
                  {proposal.context.commitments.open_task_count === 1 ? "task" : "tasks"}.
                </Text>
                <Disclosure
                  lines={[
                    ...proposal.context.why.evidence,
                    proposal.context.honesty,
                  ]}
                  title="What recorded information did Hymn use?"
                />
              </Section>

              <Section title="How much planning might help">
                <Text style={styles.depthTitle}>
                  {DEPTH_LABELS[proposal.scale.user_selected_depth || proposal.scale.recommended_depth]}
                </Text>
                <Text style={styles.body}>{proposal.scale.summary}</Text>
                <View style={styles.pillRow}>
                  {(Object.keys(DEPTH_LABELS) as PlanningDepth[]).map((depth) => (
                    <Pill
                      disabled={Boolean(busy) || proposal.status === "applied"}
                      key={depth}
                      label={DEPTH_LABELS[depth]}
                      onPress={() => void chooseDepth(depth)}
                      selected={(proposal.scale.user_selected_depth || proposal.scale.recommended_depth) === depth}
                    />
                  ))}
                </View>
                {proposal.scale.axes
                  .filter((axis) => ["financial", "duration", "conflicts"].includes(axis.id))
                  .map((axis) => (
                    <View key={axis.id} style={styles.contextLine}>
                      <Text style={styles.contextLabel}>
                        {axis.id === "financial"
                          ? "Money"
                          : axis.id === "duration"
                            ? "Timing"
                            : "Other commitments"}
                      </Text>
                      <Text style={styles.body}>{axis.summary}</Text>
                    </View>
                  ))}
                {proposal.scale.calculations.length ? (
                  <Disclosure
                    lines={proposal.scale.calculations.map(
                      (row) => `${row.label}: ${row.value}`,
                    )}
                    title="Show calculations used"
                  />
                ) : null}
              </Section>

              {proposal.research.state !== "research_not_needed" ? (
                <Section title="External requirements">
                  <Text style={styles.body}>{proposal.research.message}</Text>
                  {proposal.research.questions.map((question) => (
                    <View key={question.id} style={styles.notice}>
                      <Text style={styles.noticeTitle}>{question.question}</Text>
                      <Text style={styles.helper}>{question.why_needed}</Text>
                    </View>
                  ))}
                  {["research_recommended", "research_failed"].includes(proposal.research.state) ? (
                    <Pressable
                      disabled={Boolean(busy)}
                      onPress={async () => {
                        try {
                          setBusy("research");
                          acceptProposal(await api.chooseDreamManualResearch(
                            proposal.id,
                            proposal.revision,
                          ));
                        } catch (caught: unknown) {
                          setError(errorMessage(caught, "The manual fallback was not saved."));
                        } finally {
                          setBusy(null);
                        }
                      }}
                      style={styles.secondary}
                    >
                      <Text style={styles.secondaryText}>
                        {researchActionLabel(proposal.research.state)}
                      </Text>
                    </Pressable>
                  ) : null}
                </Section>
              ) : null}

              {!mapOpen && proposal.status !== "applied" ? (
                <View style={styles.mapInvitation}>
                  <Text style={styles.eyebrow}>A first route is ready</Text>
                  <Text style={styles.cardTitle}>
                    Open a practical map you can reshape before anything is created.
                  </Text>
                  <Text style={styles.body}>
                    {hasOpenQuestions
                      ? "Anything you are not sure about stays clearly provisional; it will not strand the journey."
                      : "Your answers are reflected in this draft. You can still change them whenever you need to."}
                  </Text>
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => setMapOpen(true)}
                    style={styles.primary}
                    testID="dream-open-map"
                  >
                    <Text style={styles.primaryText}>Open my plan map</Text>
                  </Pressable>
                </View>
              ) : null}

              {mapOpen || proposal.status === "applied" ? (
                <View
                  onLayout={(event) => setMapOffset(event.nativeEvent.layout.y)}
                  style={styles.progressiveBlock}
                >
              <Section title="Your plan map" testID="dream-plan-map">
                <View style={styles.northStar}>
                  <Text style={styles.contextLabel}>North star</Text>
                  <Text style={styles.cardTitle}>{proposal.original_text}</Text>
                </View>
                <View style={styles.modeRow}>
                  <View style={styles.pillRow}>
                    <Pill label="Map view" onPress={() => setViewMode("map")} selected={viewMode === "map"} />
                    <Pill label="Accessible list" onPress={() => setViewMode("list")} selected={viewMode === "list"} />
                  </View>
                  {proposal.status !== "applied" ? (
                    <Pressable
                      disabled={!proposal.map.can_undo || Boolean(busy)}
                      onPress={() => void operate({ type: "undo" })}
                      style={styles.textButton}
                    >
                      <Text style={[
                        styles.textButtonText,
                        (!proposal.map.can_undo || Boolean(busy)) && styles.muted,
                      ]}>Undo</Text>
                    </Pressable>
                  ) : null}
                </View>
                <Text style={styles.helper}>
                  Numbers change when you reorder. Stable plan identities and descendants do not.
                </Text>
                {proposal.status !== "applied"
                  && proposal.map.nodes.some((node) => node.decision_state === "proposed") ? (
                    <Pressable
                      disabled={Boolean(busy)}
                      onPress={() => void operate({ type: "accept_all" })}
                      style={styles.secondary}
                      testID="dream-accept-all"
                    >
                      <Text style={styles.secondaryText}>Use all suggestions</Text>
                    </Pressable>
                  ) : null}

                {moving ? (
                  <View style={styles.movePanel}>
                    <Text style={styles.noticeTitle}>Move “{moving.title}” inside…</Text>
                    <View style={styles.pillRow}>
                      {compatibleParents.map((parent) => (
                        <Pill
                          key={parent?.id || "root"}
                          label={parent ? `${parent.display_number} ${parent.title}` : "Plan root"}
                          onPress={() => void operate({
                            type: "move",
                            node_id: moving.id,
                            parent_id: parent?.id || null,
                            placement: "inside_end",
                          })}
                        />
                      ))}
                    </View>
                    <Pressable onPress={() => setMovingNode(null)} style={styles.textButton}>
                      <Text style={styles.textButtonText}>Cancel move</Text>
                    </Pressable>
                  </View>
                ) : null}

                {nodes.length ? nodes.map((node) => (
                  <View
                    accessibilityLabel={`${NODE_LABELS[node.kind]} ${node.display_number}: ${node.title}`}
                    key={node.id}
                    style={[
                      styles.nodeCard,
                      viewMode === "map" && {
                        marginLeft: Math.min(nodeDepth(node), 3) * 14,
                      },
                      node.decision_state === "deferred" && styles.nodeDeferred,
                    ]}
                    testID={`dream-node-${node.id}`}
                  >
                    <View style={styles.nodeHeader}>
                      <View style={styles.nodeNumber}>
                        <Text style={styles.nodeNumberText}>{node.display_number}</Text>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.nodeKind}>
                          {NODE_LABELS[node.kind]} · {node.origin === "user" ? "You added" : "Hymn suggested"}
                        </Text>
                        <Text style={styles.nodeTitle}>{node.title}</Text>
                        {node.description ? <Text style={styles.body}>{node.description}</Text> : null}
                        {node.kind === "checkin_requirement" && node.checkin ? (
                          <Text style={styles.helper}>
                            {node.checkin.schedule_type.replaceAll("_", " ")} · {node.checkin.question}
                          </Text>
                        ) : null}
                      </View>
                    </View>

                    {deletingNode === node.id ? (
                      <View style={styles.deletePanel}>
                        <Text style={styles.noticeTitle}>Remove “{node.title}”?</Text>
                        {proposal.map.nodes.some((row) => row.parent_id === node.id) ? (
                          <Text style={styles.body}>
                            This item contains other plan items. Keep them by moving them up one level, or remove the whole group.
                          </Text>
                        ) : (
                          <Text style={styles.body}>
                            This removes the item from the draft only. Nothing active has been created yet.
                          </Text>
                        )}
                        <View style={styles.actionRow}>
                          {proposal.map.nodes.some((row) => row.parent_id === node.id) ? (
                            <Pressable
                              accessibilityRole="button"
                              disabled={Boolean(busy)}
                              onPress={() => {
                                void operate({
                                  type: "delete",
                                  node_id: node.id,
                                  delete_mode: "reparent_children",
                                  destination_parent_id: node.parent_id,
                                }).then(() => setDeletingNode(null));
                              }}
                              style={styles.secondarySmall}
                            >
                              <Text style={styles.secondarySmallText}>Keep its children</Text>
                            </Pressable>
                          ) : null}
                          <Pressable
                            accessibilityRole="button"
                            disabled={Boolean(busy)}
                            onPress={() => {
                              void operate({
                                type: "delete",
                                node_id: node.id,
                                delete_mode: "remove_subtree",
                              }).then(() => setDeletingNode(null));
                            }}
                            style={styles.dangerSmall}
                          >
                            <Text style={styles.dangerSmallText}>
                              {proposal.map.nodes.some((row) => row.parent_id === node.id)
                                ? "Remove whole group"
                                : "Remove item"}
                            </Text>
                          </Pressable>
                          <Pressable
                            accessibilityRole="button"
                            onPress={() => setDeletingNode(null)}
                            style={styles.textButton}
                          >
                            <Text style={styles.textButtonText}>Cancel</Text>
                          </Pressable>
                        </View>
                      </View>
                    ) : null}

                    {editingNode === node.id ? (
                      <NodeEditor
                        busy={Boolean(busy)}
                        node={node}
                        onCancel={() => setEditingNode(null)}
                        onSave={(patch) => operate({ type: "update", node_id: node.id, patch })}
                      />
                    ) : proposal.status !== "applied" ? (
                      <>
                        <View style={styles.pillRow}>
                          {node.decision_state === "proposed" ? (
                            <Pill
                              label="Accept"
                              onPress={() => void operate({
                                type: "decide",
                                node_id: node.id,
                                decision_state: "accepted",
                              })}
                            />
                          ) : null}
                          <Pill label="Edit" onPress={() => setEditingNode(node.id)} />
                          <Pill
                            label={node.decision_state === "deferred" ? "Restore" : "Defer"}
                            onPress={() => void operate({
                              type: "decide",
                              node_id: node.id,
                              decision_state: node.decision_state === "deferred" ? "accepted" : "deferred",
                            })}
                          />
                          {node.origin === "hymn" ? (
                            <Pill
                              label="Reject"
                              onPress={() => void operate({
                                type: "decide",
                                node_id: node.id,
                                decision_state: "rejected",
                              })}
                            />
                          ) : (
                            <Pill label="Delete" onPress={() => deleteNode(node)} />
                          )}
                        </View>
                        <View style={styles.iconActions}>
                          <Pressable
                            accessibilityLabel={`Move ${node.title} up`}
                            onPress={() => {
                              const operation = siblingMoveOperation(proposal.map.nodes, node.id, "up");
                              if (operation) void operate(operation);
                            }}
                            style={styles.labeledIconButton}
                          >
                            <Ionicons name="arrow-up" size={17} color={colors.onSurfaceSecondary} />
                            <Text style={styles.iconButtonLabel}>Up</Text>
                          </Pressable>
                          <Pressable
                            accessibilityLabel={`Move ${node.title} down`}
                            onPress={() => {
                              const operation = siblingMoveOperation(proposal.map.nodes, node.id, "down");
                              if (operation) void operate(operation);
                            }}
                            style={styles.labeledIconButton}
                          >
                            <Ionicons name="arrow-down" size={17} color={colors.onSurfaceSecondary} />
                            <Text style={styles.iconButtonLabel}>Down</Text>
                          </Pressable>
                          <Pressable
                            accessibilityLabel={`Move ${node.title} to another parent`}
                            onPress={() => setMovingNode(node.id)}
                            style={styles.labeledIconButton}
                          >
                            <Ionicons name="git-compare-outline" size={16} color={colors.onSurfaceSecondary} />
                            <Text style={styles.iconButtonLabel}>Move</Text>
                          </Pressable>
                          <Pressable
                            accessibilityLabel={`Duplicate ${node.title}`}
                            onPress={() => void operate({ type: "duplicate", node_id: node.id })}
                            style={styles.labeledIconButton}
                          >
                            <Ionicons name="copy-outline" size={16} color={colors.onSurfaceSecondary} />
                            <Text style={styles.iconButtonLabel}>Duplicate</Text>
                          </Pressable>
                          {node.kind !== "checkin_requirement" ? (
                            <Pressable
                              accessibilityLabel={`Add inside ${node.title}`}
                              onPress={() => setAdding({
                                parentId: node.id,
                                placement: "inside_end",
                                kind: suggestedAddKind(node),
                              })}
                              style={styles.labeledIconButton}
                            >
                              <Ionicons name="add" size={17} color={colors.onSurfaceSecondary} />
                              <Text style={styles.iconButtonLabel}>Add inside</Text>
                            </Pressable>
                          ) : null}
                          <Pressable
                            accessibilityLabel={`Add after ${node.title}`}
                            onPress={() => setAdding({
                              parentId: node.parent_id,
                              relativeId: node.id,
                              placement: "after",
                              kind: node.kind,
                            })}
                            style={styles.labeledIconButton}
                          >
                            <Ionicons name="return-down-forward-outline" size={16} color={colors.onSurfaceSecondary} />
                            <Text style={styles.iconButtonLabel}>Add after</Text>
                          </Pressable>
                        </View>
                      </>
                    ) : null}
                  </View>
                )) : (
                  <View style={styles.notice}>
                    <Text style={styles.noticeTitle}>Your map is empty</Text>
                    <Text style={styles.body}>
                      Add a phase, milestone, or task. Hymn will not create an artificial structure.
                    </Text>
                  </View>
                )}

                {adding ? (
                  <AddNodeForm
                    busy={Boolean(busy)}
                    kind={adding.kind}
                    onAdd={(node) => operate({
                      type: "add",
                      node,
                      parent_id: adding.parentId,
                      relative_id: adding.relativeId,
                      placement: adding.placement,
                    })}
                    onCancel={() => setAdding(null)}
                  />
                ) : proposal.status !== "applied" ? (
                  <View style={styles.addRootRow}>
                    <Text style={styles.helper}>Add at plan root:</Text>
                    <View style={styles.pillRow}>
                      {(["phase", "milestone", "task"] as DreamNodeKind[]).map((kind) => (
                        <Pill
                          key={kind}
                          label={NODE_LABELS[kind]}
                          onPress={() => setAdding({
                            parentId: null,
                            placement: "inside_end",
                            kind,
                          })}
                        />
                      ))}
                    </View>
                  </View>
                ) : null}
              </Section>

              {proposal.status === "applied" && proposal.applied_plan ? (
                <View style={styles.successCard}>
                  <Ionicons name="checkmark-circle" size={24} color={colors.success} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.noticeTitle}>Plan attached</Text>
                    <Text style={styles.body}>
                      Hymn created this plan once. Refreshing or retrying will not duplicate it.
                    </Text>
                    {proposal.applied_plan.created_counts ? (
                      <Text style={styles.helper}>
                        {proposal.applied_plan.created_counts.phase} phases ·{" "}
                        {proposal.applied_plan.created_counts.milestone} milestones/outcomes ·{" "}
                        {proposal.applied_plan.created_counts.task} tasks ·{" "}
                        {proposal.applied_plan.created_counts.checkin_requirement} required check-ins
                      </Text>
                    ) : null}
                    {applyNotice ? <Text style={styles.savedText}>{applyNotice}</Text> : null}
                    <Pressable
                      accessibilityRole="button"
                      onPress={returnToSource}
                      style={styles.secondary}
                    >
                      <Text style={styles.secondaryText}>{proposal.applied_plan.return_to.label}</Text>
                    </Pressable>
                  </View>
                </View>
              ) : (
                <>
                  {!reviewOpen ? (
                    <Pressable
                      accessibilityRole="button"
                      disabled={Boolean(busy)}
                      onPress={openReview}
                      style={[styles.primary, Boolean(busy) && styles.disabled]}
                      testID="dream-review-plan"
                    >
                      <Text style={styles.primaryText}>Review this plan</Text>
                    </Pressable>
                  ) : (
                    <View
                      onLayout={(event) => setReviewOffset(event.nativeEvent.layout.y)}
                      style={styles.applyReview}
                      testID="dream-apply-review"
                    >
                      <Text style={styles.eyebrow}>Final review</Text>
                      <Text style={styles.sectionTitle}>Here’s what Hymn will create</Text>
                      <Text style={styles.body}>
                        Only accepted, modified, and user-added items will be included. Rejected and deferred suggestions stay in the draft history.
                      </Text>
                      {decisionCounts ? (
                        <View style={styles.decisionGrid}>
                          <Pill label={`${decisionCounts.accepted} accepted`} />
                          <Pill label={`${decisionCounts.modified} modified`} />
                          <Pill label={`${decisionCounts.user_added} you added`} />
                          <Pill label={`${decisionCounts.deferred} deferred`} />
                          <Pill label={`${decisionCounts.rejected} rejected`} />
                          <Pill label={`${decisionCounts.proposed} undecided`} />
                        </View>
                      ) : null}
                      <View style={styles.previewGroup}>
                        <Text style={styles.cardTitle}>{creationEffectCopy(proposal)}</Text>
                        {(Object.keys(proposal.creation_preview.counts) as DreamNodeKind[]).map((kind) => (
                          <View key={kind} style={styles.previewRow}>
                            <Text style={styles.body}>{NODE_LABELS[kind]}</Text>
                            <Text style={styles.previewCount}>{proposal.creation_preview.counts[kind]}</Text>
                          </View>
                        ))}
                      </View>
                      {!applyReadiness.ready ? (
                        <View style={styles.warningCard} accessibilityRole="alert">
                          <Text style={styles.warningText}>{applyReadiness.reason}</Text>
                        </View>
                      ) : (
                        <Text style={styles.successText}>
                          This revision is structurally ready. Nothing will be created until you press Apply.
                        </Text>
                      )}
                      {applyNotice ? (
                        <Text
                          accessibilityLiveRegion="polite"
                          style={styles.savedText}
                        >
                          {applyNotice}
                        </Text>
                      ) : null}
                      <View style={styles.actionRow}>
                        <Pressable
                          accessibilityRole="button"
                          disabled={Boolean(busy) || !applyReadiness.ready}
                          onPress={() => void apply()}
                          style={[
                            styles.primary,
                            { flex: 1 },
                            (Boolean(busy) || !applyReadiness.ready) && styles.disabled,
                          ]}
                          testID="dream-apply"
                        >
                          {busy === "apply" ? (
                            <ActivityIndicator color={colors.onBrandPrimary} />
                          ) : (
                            <Text style={styles.primaryText}>Apply this plan</Text>
                          )}
                        </Pressable>
                        <Pressable
                          accessibilityRole="button"
                          disabled={Boolean(busy)}
                          onPress={() => {
                            setReviewOpen(false);
                            requestAnimationFrame(() => {
                              scrollRef.current?.scrollTo({
                                y: Math.max(0, mapOffset - spacing.lg),
                                animated: !reducedMotion,
                              });
                            });
                          }}
                          style={styles.secondarySmall}
                        >
                          <Text style={styles.secondarySmallText}>Keep editing</Text>
                        </Pressable>
                      </View>
                    </View>
                  )}
                </>
              )}
                </View>
              ) : null}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  eyebrow: {
    color: colors.brandPrimary, fontSize: 12, fontWeight: "700",
    letterSpacing: 0.8, textTransform: "uppercase",
  },
  headerTitle: { color: colors.onSurface, fontFamily: fonts.display, fontSize: 24 },
  scroll: {
    alignSelf: "center", gap: spacing.lg, maxWidth: 920,
    padding: spacing.lg, paddingBottom: 80, width: "100%",
  },
  hero: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.lg,
    padding: spacing.xl, gap: spacing.md,
  },
  conversationHero: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.lg,
    gap: spacing.md, padding: spacing.xl,
  },
  heroTitle: { color: colors.onSurface, fontFamily: fonts.display, fontSize: 30, lineHeight: 36 },
  quote: { color: colors.onSurfaceSecondary, fontFamily: fonts.display, fontSize: 19, lineHeight: 27 },
  body: { color: colors.onSurfaceSecondary, fontSize: 15, lineHeight: 22 },
  muted: { color: colors.onSurfaceTertiary, fontSize: 13, lineHeight: 19 },
  helper: { color: colors.onSurfaceTertiary, fontSize: 12, lineHeight: 18 },
  composer: {
    minHeight: 132, maxHeight: 260, backgroundColor: colors.surface,
    borderColor: colors.borderStrong, borderRadius: radius.md, borderWidth: 1,
    color: colors.onSurface, fontSize: 18, lineHeight: 27, padding: spacing.lg,
    textAlignVertical: "top",
  },
  counter: { color: colors.onSurfaceTertiary, fontSize: 11, textAlign: "right" },
  label: {
    color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700",
    marginTop: spacing.sm, textTransform: "uppercase",
  },
  shapeGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md },
  shapeTile: {
    backgroundColor: colors.surfaceSecondary, borderColor: colors.border,
    borderRadius: radius.md, borderWidth: 1, minWidth: 210,
    padding: spacing.md, flexBasis: "48%", flexGrow: 1,
  },
  shapeTileSelected: { backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary },
  shapeTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  shapeDescription: { color: colors.onSurfaceSecondary, fontSize: 12, lineHeight: 17, marginTop: 4 },
  primary: {
    alignItems: "center", backgroundColor: colors.brandPrimary,
    borderRadius: radius.md, minHeight: 52, justifyContent: "center", padding: spacing.md,
  },
  primaryText: { color: colors.onBrandPrimary, fontSize: 16, fontWeight: "700" },
  secondary: {
    alignItems: "center", borderColor: colors.borderStrong, borderRadius: radius.md,
    borderWidth: 1, minHeight: 44, justifyContent: "center",
    marginTop: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
  },
  secondaryText: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.45 },
  errorCard: {
    alignItems: "center", backgroundColor: "#FBEDE9", borderRadius: radius.md,
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
  },
  errorText: { color: colors.error, flex: 1, fontSize: 14, lineHeight: 20 },
  section: {
    backgroundColor: colors.surface, borderColor: colors.border,
    borderRadius: radius.lg, borderWidth: 1, padding: spacing.lg, gap: spacing.md,
  },
  sectionTitle: { color: colors.onSurface, fontFamily: fonts.display, fontSize: 24 },
  sectionIntro: { color: colors.onSurfaceSecondary, fontSize: 14, lineHeight: 21 },
  cardTitle: { color: colors.onSurface, fontSize: 16, fontWeight: "700" },
  depthTitle: { color: colors.onSurface, fontFamily: fonts.display, fontSize: 27 },
  metric: { color: colors.onSurface, fontFamily: fonts.display, fontSize: 28 },
  questionCard: {
    backgroundColor: colors.surfaceSecondary, borderColor: colors.border,
    borderRadius: radius.md, borderWidth: 1, gap: spacing.sm, padding: spacing.lg,
  },
  questionCardAnswered: {
    backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary,
  },
  questionTitle: { color: colors.onSurface, fontSize: 17, fontWeight: "700" },
  questionAnswer: { color: colors.onSurface, fontSize: 15, lineHeight: 22 },
  questionInputs: { gap: spacing.sm },
  moneyInputs: { flexDirection: "row", gap: spacing.sm },
  currencyInput: { maxWidth: 100, textAlign: "center" },
  savedText: { color: colors.success, fontSize: 13, fontWeight: "600", lineHeight: 19 },
  contextHighlight: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    gap: spacing.xs, padding: spacing.lg,
  },
  contextLabel: {
    color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700",
    letterSpacing: 0.5, textTransform: "uppercase",
  },
  contextLine: {
    borderTopColor: colors.border, borderTopWidth: 1,
    gap: spacing.xs, paddingTop: spacing.sm,
  },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  pill: {
    borderColor: colors.borderStrong, borderRadius: radius.pill, borderWidth: 1,
    paddingHorizontal: spacing.md, paddingVertical: 7,
  },
  pillSelected: { backgroundColor: colors.onSurface, borderColor: colors.onSurface },
  pillText: { color: colors.onSurfaceSecondary, fontSize: 12, textTransform: "capitalize" },
  pillTextSelected: { color: colors.onSurfaceInverse },
  disclosure: { borderTopColor: colors.border, borderTopWidth: 1, marginTop: spacing.sm },
  disclosureButton: {
    alignItems: "center", flexDirection: "row", justifyContent: "space-between",
    paddingVertical: spacing.md,
  },
  disclosureTitle: { color: colors.onSurfaceSecondary, fontSize: 13, fontWeight: "700" },
  disclosureBody: { gap: spacing.xs, paddingBottom: spacing.sm },
  factRow: {
    alignItems: "flex-start", borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: "row",
    gap: spacing.md, paddingVertical: spacing.md,
  },
  factLabel: { color: colors.onSurfaceTertiary, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  factValue: { color: colors.onSurface, fontSize: 16, marginTop: 3 },
  factSource: { color: colors.brandPrimary, fontSize: 11, marginTop: 3 },
  input: {
    backgroundColor: colors.surface, borderColor: colors.borderStrong,
    borderRadius: radius.sm, borderWidth: 1, color: colors.onSurface,
    fontSize: 15, minHeight: 44, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  multiline: { minHeight: 84, textAlignVertical: "top" },
  inlineActions: { alignItems: "flex-end" },
  textButton: { paddingHorizontal: spacing.sm, paddingVertical: spacing.sm },
  textButtonText: { color: colors.onSurfaceSecondary, fontSize: 13, fontWeight: "600" },
  textButtonStrong: { color: colors.brandPrimary, fontSize: 13, fontWeight: "700" },
  notice: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, gap: spacing.xs, padding: spacing.md },
  noticeTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  successText: { color: colors.success, fontSize: 14 },
  warningCard: { backgroundColor: "#FFF4E5", borderRadius: radius.md, padding: spacing.md },
  warningText: { color: "#7A4D16", fontSize: 13, lineHeight: 19 },
  axisRow: { borderTopColor: colors.border, borderTopWidth: 1, gap: 4, paddingTop: spacing.sm },
  mapInvitation: {
    backgroundColor: colors.surfaceSecondary, borderColor: colors.borderStrong,
    borderRadius: radius.lg, borderWidth: 1, gap: spacing.md, padding: spacing.xl,
  },
  progressiveBlock: { gap: spacing.lg },
  northStar: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    gap: spacing.xs, padding: spacing.md,
  },
  modeRow: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  movePanel: { backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.md },
  deletePanel: {
    backgroundColor: "#FBEDE9", borderRadius: radius.md,
    gap: spacing.sm, marginTop: spacing.sm, padding: spacing.md,
  },
  dangerSmall: {
    alignItems: "center", backgroundColor: colors.error,
    borderRadius: radius.md, justifyContent: "center",
    minHeight: 42, paddingHorizontal: spacing.md,
  },
  dangerSmallText: { color: colors.onSurfaceInverse, fontSize: 13, fontWeight: "700" },
  nodeCard: {
    backgroundColor: colors.surfaceSecondary, borderColor: colors.border,
    borderRadius: radius.md, borderWidth: 1, gap: spacing.sm, padding: spacing.md,
  },
  nodeDeferred: { opacity: 0.62 },
  nodeHeader: { alignItems: "flex-start", flexDirection: "row", gap: spacing.md },
  nodeNumber: {
    alignItems: "center", backgroundColor: colors.onSurface, borderRadius: radius.pill,
    justifyContent: "center", minHeight: 30, minWidth: 30, paddingHorizontal: 8,
  },
  nodeNumberText: { color: colors.onSurfaceInverse, fontSize: 11, fontWeight: "700" },
  nodeKind: { color: colors.brandPrimary, fontSize: 10, fontWeight: "700", textTransform: "uppercase" },
  nodeTitle: { color: colors.onSurface, fontSize: 16, fontWeight: "700", marginVertical: 3 },
  nodeEditor: { borderTopColor: colors.borderStrong, borderTopWidth: 1, gap: spacing.sm, paddingTop: spacing.md },
  actionRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  primarySmall: { backgroundColor: colors.brandPrimary, borderRadius: radius.sm, padding: spacing.md },
  primarySmallText: { color: colors.onBrandPrimary, fontSize: 13, fontWeight: "700" },
  secondarySmall: { borderColor: colors.borderStrong, borderRadius: radius.sm, borderWidth: 1, padding: spacing.md },
  secondarySmallText: { color: colors.onSurfaceSecondary, fontSize: 13, fontWeight: "700" },
  iconActions: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  iconButton: {
    alignItems: "center", borderColor: colors.border, borderRadius: radius.sm,
    borderWidth: 1, height: 34, justifyContent: "center", width: 34,
  },
  labeledIconButton: {
    alignItems: "center", borderColor: colors.border, borderRadius: radius.sm,
    borderWidth: 1, flexDirection: "row", gap: 4, minHeight: 34,
    paddingHorizontal: spacing.sm,
  },
  iconButtonLabel: { color: colors.onSurfaceSecondary, fontSize: 11 },
  addForm: { backgroundColor: colors.brandTertiary, borderRadius: radius.md, gap: spacing.sm, padding: spacing.md },
  addRootRow: { borderTopColor: colors.border, borderTopWidth: 1, paddingTop: spacing.md },
  previewRow: {
    alignItems: "center", borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: "row",
    justifyContent: "space-between", paddingVertical: spacing.sm,
  },
  previewCount: { color: colors.onSurface, fontSize: 16, fontWeight: "700" },
  applyReview: {
    backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary,
    borderRadius: radius.lg, borderWidth: 1, gap: spacing.md, padding: spacing.xl,
  },
  decisionGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  previewGroup: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    gap: spacing.sm, padding: spacing.md,
  },
  successCard: {
    alignItems: "flex-start", backgroundColor: "#EDF5EE", borderRadius: radius.lg,
    flexDirection: "row", gap: spacing.md, padding: spacing.lg,
  },
});
