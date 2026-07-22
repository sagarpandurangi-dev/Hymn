import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

type Journey = {
  id: string; goal_id: string; journey_type: string; has_stages: boolean;
  title: string; notes: string; deadline: string; status: string; checkin_cadence: string;
  domain_name: string;
  expected_outcomes_total: number; expected_outcomes_completed: number; completion_pct: number;
};
type Stage = { id: string; journey_id: string; name: string; sequence: number };
type Component = {
  id: string; journey_id: string; stage_id: string | null; parent_component_id: string | null;
  name: string; type: string; sequence: number; status: string; progress: number; notes: string;
};
type EO = { id: string; title: string; target_value: string; current_value: string; unit: string; status: string };
type Task = { id: string; title: string; due_date: string; priority: string; status: string; expected_outcome_id: string | null; component_id: string | null };
type Checkin = { id: string; title: string; date: string; time: string; component_id: string | null };

const JOURNEY_TYPE_LABEL: Record<string, string> = {
  professional_qualification: "Qualification",
  skill: "Skill",
  course: "Course",
  subject: "Subject",
  book: "Book",
  custom: "Custom",
};
const COMP_STATUSES = ["not_started", "in_progress", "completed", "paused"] as const;
const STATUS_COLORS: Record<string, string> = {
  not_started: colors.onSurfaceTertiary,
  in_progress: colors.brandPrimary,
  completed: colors.success,
  paused: colors.warning,
  active: colors.brandPrimary,
};

function formatDateShort(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch { return iso; }
}
function cadenceLabel(c: string): string { return c ? c[0].toUpperCase() + c.slice(1) : ""; }
function statusLabel(s: string): string { return s.replace(/_/g, " "); }

// ---------------- Component add/edit sheet ----------------
type SheetState = {
  mode: "add-child" | "edit";
  component?: Component;
  stageId: string | null;
  parentId: string | null;
  journeyId: string;
};

function ComponentSheet({
  visible, initial, onClose, onSaved,
}: {
  visible: boolean;
  initial: SheetState | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(""); const [type, setType] = useState("");
  const [status, setStatus] = useState<string>("not_started"); const [progress, setProgress] = useState<string>("0");
  const [notes, setNotes] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    if (initial?.mode === "edit" && initial.component) {
      const c = initial.component;
      setName(c.name); setType(c.type); setStatus(c.status);
      setProgress(String(c.progress || 0)); setNotes(c.notes); setErr(null);
    } else {
      setName(""); setType(""); setStatus("not_started"); setProgress("0"); setNotes(""); setErr(null);
    }
  }, [visible, initial?.component?.id, initial?.mode]);

  const save = async (journeyId: string) => {
    setErr(null);
    if (!journeyId) { setErr("Missing journey context. Please retry."); return; }
    if (!name.trim()) { setErr("Name is required."); return; }
    const p = parseInt(progress || "0", 10);
    if (isNaN(p) || p < 0 || p > 100) { setErr("Progress must be 0-100."); return; }
    setBusy(true);
    try {
      if (initial?.mode === "edit" && initial.component) {
        await api.updateComponent(initial.component.id, { name: name.trim(), type: type.trim(), status, progress: p, notes: notes.trim() });
      } else {
        await api.createComponent({
          journey_id: journeyId,
          stage_id: initial?.stageId ?? null,
          parent_component_id: initial?.parentId ?? null,
          name: name.trim(), type: type.trim(), status, progress: p, notes: notes.trim(),
        });
      }
      await onSaved();
      onClose();
    } catch (e: any) {
      setErr(typeof e?.message === "string" ? e.message : "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.backdrop}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end" }}>
          <View style={sheetStyles.sheet}>
            <View style={sheetStyles.headerRow}>
              <Pressable onPress={onClose} hitSlop={12} testID="comp-sheet-cancel"><Text style={sheetStyles.cancel}>Cancel</Text></Pressable>
              <Text style={sheetStyles.title}>{initial?.mode === "edit" ? "Edit component" : "New component"}</Text>
              <View style={{ width: 60 }} />
            </View>
            <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
              <Text style={sheetStyles.label}>Name</Text>
              <TextInput style={sheetStyles.input} value={name} onChangeText={setName} placeholder="e.g. Chapter 1, Chords, FR" placeholderTextColor={colors.onSurfaceTertiary} testID="comp-sheet-name" autoFocus />
              <Text style={sheetStyles.label}>Type (optional)</Text>
              <TextInput style={sheetStyles.input} value={type} onChangeText={setType} placeholder="e.g. Chapter, Chord, Paper" placeholderTextColor={colors.onSurfaceTertiary} testID="comp-sheet-type" />
              <Text style={sheetStyles.label}>Status</Text>
              <View style={sheetStyles.chipRow}>
                {COMP_STATUSES.map((s) => {
                  const sel = status === s;
                  return (
                    <Pressable key={s} onPress={() => setStatus(s)} style={[sheetStyles.chip, sel && sheetStyles.chipSel]} testID={`comp-sheet-status-${s}`}>
                      <Text style={[sheetStyles.chipText, sel && sheetStyles.chipTextSel]}>{statusLabel(s)}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={sheetStyles.label}>Progress (0-100)</Text>
              <TextInput style={sheetStyles.input} value={progress} onChangeText={setProgress} placeholder="0" keyboardType="number-pad" placeholderTextColor={colors.onSurfaceTertiary} testID="comp-sheet-progress" />
              <Text style={sheetStyles.label}>Notes (optional)</Text>
              <TextInput style={sheetStyles.notes} value={notes} onChangeText={setNotes} multiline textAlignVertical="top" placeholder="Anything worth remembering" placeholderTextColor={colors.onSurfaceTertiary} testID="comp-sheet-notes" />
              {err ? <Text style={sheetStyles.err} testID="comp-sheet-error">{err}</Text> : null}
            </ScrollView>
            <Pressable onPress={() => initial ? save(initial.journeyId) : null} disabled={busy} style={[sheetStyles.cta, busy && { opacity: 0.5 }]} testID="comp-sheet-save">
              {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={sheetStyles.ctaText}>Save</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

// ---------------- Stage add/edit sheet ----------------
function StageSheet({
  visible, initialName, onClose, onSubmit,
}: {
  visible: boolean; initialName: string; onClose: () => void; onSubmit: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (visible) { setName(initialName); setErr(null); }
  }, [visible, initialName]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={sheetStyles.backdrop}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end" }}>
          <View style={sheetStyles.sheet}>
            <View style={sheetStyles.headerRow}>
              <Pressable onPress={onClose} hitSlop={12} testID="stage-sheet-cancel"><Text style={sheetStyles.cancel}>Cancel</Text></Pressable>
              <Text style={sheetStyles.title}>{initialName ? "Rename stage" : "New stage"}</Text>
              <View style={{ width: 60 }} />
            </View>
            <Text style={sheetStyles.label}>Stage name</Text>
            <TextInput style={sheetStyles.input} value={name} onChangeText={setName} placeholder="e.g. Foundation, Level 1" placeholderTextColor={colors.onSurfaceTertiary} testID="stage-sheet-name" autoFocus />
            {err ? <Text style={sheetStyles.err}>{err}</Text> : null}
            <Pressable
              onPress={async () => {
                if (!name.trim()) { setErr("Name is required."); return; }
                setBusy(true);
                try { await onSubmit(name.trim()); onClose(); } catch (e: any) { setErr(e?.message || "Save failed"); } finally { setBusy(false); }
              }}
              disabled={busy}
              style={[sheetStyles.cta, busy && { opacity: 0.5 }]}
              testID="stage-sheet-save"
            >
              {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={sheetStyles.ctaText}>Save</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

// ---------------- Recursive tree node ----------------
function ComponentNode({
  comp, depth, allComponents, expandedIds, toggle, onAddChild, onEdit, onDelete, onMove, isFirst, isLast,
}: {
  comp: Component;
  depth: number;
  allComponents: Component[];
  expandedIds: Set<string>;
  toggle: (id: string) => void;
  onAddChild: (parent: Component) => void;
  onEdit: (c: Component) => void;
  onDelete: (c: Component) => void;
  onMove: (c: Component, dir: "up" | "down") => void;
  isFirst: boolean; isLast: boolean;
}) {
  const children = useMemo(
    () => allComponents.filter((c) => c.parent_component_id === comp.id).sort((a, b) => a.sequence - b.sequence),
    [allComponents, comp.id],
  );
  const isOpen = expandedIds.has(comp.id);
  const hasChildren = children.length > 0;
  return (
    <View style={{ marginLeft: depth * 12 }}>
      <View style={styles.nodeRow} testID={`comp-node-${comp.id}`}>
        <Pressable onPress={() => hasChildren && toggle(comp.id)} hitSlop={6} style={styles.chevBtn}>
          <Ionicons
            name={hasChildren ? (isOpen ? "chevron-down" : "chevron-forward") : "ellipse"}
            size={hasChildren ? 16 : 6}
            color={hasChildren ? colors.onSurfaceSecondary : colors.onSurfaceTertiary}
          />
        </Pressable>
        <View style={{ flex: 1 }}>
          <View style={styles.nodeTitleRow}>
            <Text style={styles.nodeName} numberOfLines={1}>{comp.name}</Text>
            {comp.type ? <Text style={styles.nodeType}>· {comp.type}</Text> : null}
          </View>
          <View style={styles.nodeMetaRow}>
            <View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[comp.status] || colors.onSurfaceTertiary }]} />
            <Text style={styles.nodeMeta}>{statusLabel(comp.status)}</Text>
            {comp.progress > 0 ? <Text style={styles.nodeMeta}> · {comp.progress}%</Text> : null}
          </View>
        </View>
        <View style={styles.nodeActions}>
          <Pressable onPress={() => onMove(comp, "up")} disabled={isFirst} style={isFirst ? styles.disabledIcon : undefined} hitSlop={4} testID={`comp-up-${comp.id}`}>
            <Ionicons name="arrow-up" size={14} color={colors.onSurfaceSecondary} />
          </Pressable>
          <Pressable onPress={() => onMove(comp, "down")} disabled={isLast} style={isLast ? styles.disabledIcon : undefined} hitSlop={4} testID={`comp-down-${comp.id}`}>
            <Ionicons name="arrow-down" size={14} color={colors.onSurfaceSecondary} />
          </Pressable>
          <Pressable onPress={() => onAddChild(comp)} hitSlop={4} testID={`comp-add-child-${comp.id}`}>
            <Ionicons name="add-circle-outline" size={16} color={colors.brandPrimary} />
          </Pressable>
          <Pressable onPress={() => onEdit(comp)} hitSlop={4} testID={`comp-edit-${comp.id}`}>
            <Ionicons name="pencil-outline" size={14} color={colors.onSurfaceSecondary} />
          </Pressable>
          <Pressable onPress={() => onDelete(comp)} hitSlop={4} testID={`comp-delete-${comp.id}`}>
            <Ionicons name="trash-outline" size={14} color={colors.error} />
          </Pressable>
        </View>
      </View>
      {isOpen && hasChildren && (
        <View>
          {children.map((child, i) => (
            <ComponentNode
              key={child.id}
              comp={child}
              depth={depth + 1}
              allComponents={allComponents}
              expandedIds={expandedIds}
              toggle={toggle}
              onAddChild={onAddChild}
              onEdit={onEdit}
              onDelete={onDelete}
              onMove={onMove}
              isFirst={i === 0}
              isLast={i === children.length - 1}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------- Main detail screen ----------------
export default function KnowledgeJourneyDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [journey, setJourney] = useState<Journey | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [eos, setEos] = useState<EO[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [checkins, setCheckins] = useState<Checkin[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const [compSheet, setCompSheet] = useState<SheetState | null>(null);
  const [stageSheetVisible, setStageSheetVisible] = useState(false);
  const [stageEditing, setStageEditing] = useState<Stage | null>(null);
  const [confirmDeleteStage, setConfirmDeleteStage] = useState<Stage | null>(null);
  const [confirmDeleteComp, setConfirmDeleteComp] = useState<Component | null>(null);
  const [confirmDeleteJourney, setConfirmDeleteJourney] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const j = (await api.getLearningJourney(id)) as Journey;
      setJourney(j);
      const [ss, cs, eoList, tList, ciList] = await Promise.all([
        api.listStages(id),
        api.listComponents(id),
        api.listExpectedOutcomes(j.goal_id),
        api.listTasks({ goalId: j.goal_id }),
        api.listCheckins({ goalId: j.goal_id }),
      ]);
      setStages(ss as Stage[]);
      setComponents(cs as Component[]);
      setEos(eoList as EO[]);
      setTasks(tList as Task[]);
      setCheckins(ciList as Checkin[]);
    } catch (e: any) {
      setError(e?.message || "Could not load journey");
    } finally { setLoading(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const toggle = (nid: string) => setExpandedIds((prev) => {
    const s = new Set(prev);
    if (s.has(nid)) s.delete(nid); else s.add(nid);
    return s;
  });

  const doDeleteComp = async () => {
    if (!confirmDeleteComp) return;
    await api.deleteComponent(confirmDeleteComp.id);
    setConfirmDeleteComp(null);
    await load();
  };
  const doDeleteStage = async () => {
    if (!confirmDeleteStage) return;
    await api.deleteStage(confirmDeleteStage.id);
    setConfirmDeleteStage(null);
    await load();
  };
  const doDeleteJourney = async () => {
    if (!id) return;
    await api.deleteLearningJourney(id);
    setConfirmDeleteJourney(false);
    router.replace("/(tabs)/knowledge");
  };
  const moveStage = async (s: Stage, dir: "up" | "down") => { await api.moveStage(s.id, dir); await load(); };
  const moveComponent = async (c: Component, dir: "up" | "down") => { await api.moveComponent(c.id, dir); await load(); };

  // Tree building
  const componentsByStage = useMemo(() => {
    const map = new Map<string | null, Component[]>();
    components.forEach((c) => {
      if (c.parent_component_id) return; // top-level only in this map
      const k = c.stage_id;
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(c);
    });
    map.forEach((arr) => arr.sort((a, b) => a.sequence - b.sequence));
    return map;
  }, [components]);
  const unstagedTop = componentsByStage.get(null) || [];

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>;
  }
  if (error || !journey) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><Text style={styles.errorText}>{error || "Not found"}</Text></View></SafeAreaView>;
  }

  const typeLabel = journey.journey_type ? JOURNEY_TYPE_LABEL[journey.journey_type] || "Learning Journey" : "Learning Journey";

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="knowledge-journey-detail">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="kj-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={styles.headerActions}>
          <Pressable onPress={() => router.push(`/goals/edit/${journey.goal_id}`)} testID="kj-edit-goal" hitSlop={12}>
            <Text style={styles.edit}>Edit</Text>
          </Pressable>
          <Pressable onPress={() => setConfirmDeleteJourney(true)} testID="kj-delete" hitSlop={12}>
            <Ionicons name="trash-outline" size={20} color={colors.error} />
          </Pressable>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
      >
        <Text style={styles.tag}>{typeLabel.toUpperCase()}</Text>
        <Text style={styles.title} testID="kj-title">{journey.title}</Text>

        <View style={styles.chipRow}>
          {journey.deadline ? (
            <View style={styles.chip}><Ionicons name="calendar-outline" size={13} color={colors.onSurfaceSecondary} /><Text style={styles.chipText}>by {formatDateShort(journey.deadline)}</Text></View>
          ) : null}
          {journey.checkin_cadence ? (
            <View style={styles.chip}><Ionicons name="repeat-outline" size={13} color={colors.onSurfaceSecondary} /><Text style={styles.chipText}>{cadenceLabel(journey.checkin_cadence)} check-ins</Text></View>
          ) : null}
          <View style={styles.chip}><View style={[styles.statusDot, { backgroundColor: STATUS_COLORS[journey.status] || colors.brandPrimary }]} /><Text style={styles.chipText}>{journey.status}</Text></View>
        </View>

        {/* Progress from Goal */}
        <View style={styles.progressBlock}>
          <Text style={styles.sectionLabel}>PROGRESS</Text>
          <Text style={styles.progressText}>
            <Text style={styles.progressBig}>{journey.expected_outcomes_completed}</Text>
            <Text style={styles.progressBig}> / {journey.expected_outcomes_total}</Text>
            <Text style={styles.progressSmall}>  ·  {journey.completion_pct}%</Text>
          </Text>
          <View style={styles.progressBarTrack}>
            <View style={[styles.progressBarFill, { width: `${Math.min(journey.completion_pct, 100)}%` }]} />
          </View>
        </View>

        <Pressable
          onPress={() => router.push(`/planning/journey/${journey.id}` as any)}
          testID="kj-plan-btn"
          style={styles.planBtn}
        >
          <Ionicons name="git-network-outline" size={18} color={colors.onBrandPrimary} />
          <Text style={styles.planBtnText}>Plan with Hymn</Text>
        </Pressable>

        {journey.notes ? (
          <View style={styles.block}>
            <Text style={styles.sectionLabel}>WHY THIS MATTERS</Text>
            <Text style={styles.notesText}>{journey.notes}</Text>
          </View>
        ) : null}

        {/* ---- STRUCTURE (Stages / Components) ---- */}
        <View style={styles.section}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionLabel}>STRUCTURE</Text>
            {journey.has_stages ? (
              <Pressable onPress={() => { setStageEditing(null); setStageSheetVisible(true); }} hitSlop={8} testID="kj-add-stage">
                <View style={styles.addStructureBtn}>
                  <Ionicons name="add" size={14} color={colors.onSurface} />
                  <Text style={styles.addStructureText}>Stage</Text>
                </View>
              </Pressable>
            ) : (
              <Pressable
                onPress={() => setCompSheet({ mode: "add-child", stageId: null, parentId: null, journeyId: journey.id })}
                hitSlop={8}
                testID="kj-add-component"
              >
                <View style={styles.addStructureBtn}>
                  <Ionicons name="add" size={14} color={colors.onSurface} />
                  <Text style={styles.addStructureText}>Component</Text>
                </View>
              </Pressable>
            )}
          </View>

          {journey.has_stages ? (
            stages.length === 0 ? (
              <Text style={styles.emptyLine}>No stages yet.</Text>
            ) : (
              stages.map((s, sIdx) => {
                const stageComponents = componentsByStage.get(s.id) || [];
                return (
                  <View key={s.id} style={styles.stageBlock} testID={`kj-stage-${s.id}`}>
                    <View style={styles.stageHead}>
                      <Text style={styles.stageName}>{s.name}</Text>
                      <View style={styles.stageActions}>
                        <Pressable onPress={() => moveStage(s, "up")} disabled={sIdx === 0} style={sIdx === 0 ? styles.disabledIcon : undefined} hitSlop={4} testID={`kj-stage-up-${s.id}`}>
                          <Ionicons name="arrow-up" size={14} color={colors.onSurfaceSecondary} />
                        </Pressable>
                        <Pressable onPress={() => moveStage(s, "down")} disabled={sIdx === stages.length - 1} style={sIdx === stages.length - 1 ? styles.disabledIcon : undefined} hitSlop={4} testID={`kj-stage-down-${s.id}`}>
                          <Ionicons name="arrow-down" size={14} color={colors.onSurfaceSecondary} />
                        </Pressable>
                        <Pressable onPress={() => setCompSheet({ mode: "add-child", stageId: s.id, parentId: null, journeyId: journey.id })} hitSlop={4} testID={`kj-stage-add-comp-${s.id}`}>
                          <Ionicons name="add-circle-outline" size={16} color={colors.brandPrimary} />
                        </Pressable>
                        <Pressable onPress={() => { setStageEditing(s); setStageSheetVisible(true); }} hitSlop={4} testID={`kj-stage-edit-${s.id}`}>
                          <Ionicons name="pencil-outline" size={14} color={colors.onSurfaceSecondary} />
                        </Pressable>
                        <Pressable onPress={() => setConfirmDeleteStage(s)} hitSlop={4} testID={`kj-stage-delete-${s.id}`}>
                          <Ionicons name="trash-outline" size={14} color={colors.error} />
                        </Pressable>
                      </View>
                    </View>
                    {stageComponents.length === 0 ? (
                      <Text style={[styles.emptyLine, { marginTop: 4 }]}>No components in this stage.</Text>
                    ) : (
                      stageComponents.map((c, i) => (
                        <ComponentNode
                          key={c.id}
                          comp={c}
                          depth={0}
                          allComponents={components}
                          expandedIds={expandedIds}
                          toggle={toggle}
                          onAddChild={(parent) => setCompSheet({ mode: "add-child", stageId: parent.stage_id, parentId: parent.id, journeyId: journey.id })}
                          onEdit={(comp) => setCompSheet({ mode: "edit", component: comp, stageId: comp.stage_id, parentId: comp.parent_component_id, journeyId: journey.id })}
                          onDelete={(comp) => setConfirmDeleteComp(comp)}
                          onMove={moveComponent}
                          isFirst={i === 0}
                          isLast={i === stageComponents.length - 1}
                        />
                      ))
                    )}
                  </View>
                );
              })
            )
          ) : (
            unstagedTop.length === 0 ? (
              <Text style={styles.emptyLine}>No components yet.</Text>
            ) : (
              unstagedTop.map((c, i) => (
                <ComponentNode
                  key={c.id}
                  comp={c}
                  depth={0}
                  allComponents={components}
                  expandedIds={expandedIds}
                  toggle={toggle}
                  onAddChild={(parent) => setCompSheet({ mode: "add-child", stageId: parent.stage_id, parentId: parent.id, journeyId: journey.id })}
                  onEdit={(comp) => setCompSheet({ mode: "edit", component: comp, stageId: comp.stage_id, parentId: comp.parent_component_id, journeyId: journey.id })}
                  onDelete={(comp) => setConfirmDeleteComp(comp)}
                  onMove={moveComponent}
                  isFirst={i === 0}
                  isLast={i === unstagedTop.length - 1}
                />
              ))
            )
          )}
        </View>

        {/* ---- EXPECTED OUTCOMES ---- */}
        <View style={styles.section}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionLabel}>EXPECTED OUTCOMES</Text>
            <Pressable onPress={() => router.push(`/expected-outcomes/add?goalId=${journey.goal_id}`)} hitSlop={8} testID="kj-add-eo">
              <Ionicons name="add-circle-outline" size={20} color={colors.brandPrimary} />
            </Pressable>
          </View>
          {eos.length === 0 ? <Text style={styles.emptyLine}>None yet.</Text> :
            eos.map((eo) => (
              <Pressable key={eo.id} style={styles.leafRow} onPress={() => router.push(`/expected-outcomes/edit/${eo.id}`)} testID={`kj-eo-${eo.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.leafTitle}>{eo.title}</Text>
                  <Text style={styles.leafMeta}>{(eo.current_value || "0")}/{eo.target_value || "—"} {eo.unit} · {eo.status}</Text>
                </View>
              </Pressable>
            ))
          }
        </View>

        {/* ---- TASKS ---- */}
        <View style={styles.section}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionLabel}>TASKS</Text>
          </View>
          {tasks.length === 0 ? <Text style={styles.emptyLine}>None yet.</Text> :
            tasks.map((t) => (
              <Pressable key={t.id} style={styles.leafRow} onPress={() => router.push(`/tasks/${t.id}`)} testID={`kj-task-${t.id}`}>
                <Ionicons name={t.status === "done" ? "checkmark-circle" : "ellipse-outline"} size={16} color={t.status === "done" ? colors.success : colors.onSurfaceTertiary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.leafTitle} numberOfLines={1}>{t.title}</Text>
                  <Text style={styles.leafMeta}>{t.priority} · {t.status}{t.due_date ? ` · due ${formatDateShort(t.due_date)}` : ""}</Text>
                </View>
              </Pressable>
            ))
          }
        </View>

        {/* ---- CHECK-INS ---- */}
        <View style={styles.section}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionLabel}>CHECK-INS</Text>
          </View>
          {checkins.length === 0 ? <Text style={styles.emptyLine}>None yet.</Text> :
            checkins.slice(0, 20).map((c) => (
              <Pressable key={c.id} style={styles.leafRow} onPress={() => router.push(`/checkin/${c.id}`)} testID={`kj-checkin-${c.id}`}>
                <View style={styles.checkinDot} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.leafTitle} numberOfLines={1}>{c.title || "(untitled)"}</Text>
                  <Text style={styles.leafMeta}>{formatDateShort(c.date)}{c.time ? ` · ${c.time}` : ""}</Text>
                </View>
              </Pressable>
            ))
          }
        </View>
      </ScrollView>

      <ComponentSheet visible={!!compSheet} initial={compSheet} onClose={() => setCompSheet(null)} onSaved={load} />
      <StageSheet
        visible={stageSheetVisible}
        initialName={stageEditing?.name || ""}
        onClose={() => { setStageSheetVisible(false); setStageEditing(null); }}
        onSubmit={async (name) => {
          if (stageEditing) await api.updateStage(stageEditing.id, { name });
          else await api.createStage({ journey_id: journey.id, name });
          await load();
        }}
      />
      <ConfirmModal visible={!!confirmDeleteStage} title={`Delete stage "${confirmDeleteStage?.name || ""}"?`} message="This deletes the stage and every component inside it." confirmLabel="Delete" danger onCancel={() => setConfirmDeleteStage(null)} onConfirm={doDeleteStage} testID="kj-stage-delete-modal" />
      <ConfirmModal visible={!!confirmDeleteComp} title={`Delete "${confirmDeleteComp?.name || ""}"?`} message="This deletes this component and all its children. Attached tasks and check-ins will be detached (not deleted)." confirmLabel="Delete" danger onCancel={() => setConfirmDeleteComp(null)} onConfirm={doDeleteComp} testID="kj-comp-delete-modal" />
      <ConfirmModal visible={confirmDeleteJourney} title={`Delete "${journey.title}"?`} message="This deletes the journey, all its stages, components, expected outcomes and tasks." confirmLabel="Delete" danger onCancel={() => setConfirmDeleteJourney(false)} onConfirm={doDeleteJourney} testID="kj-journey-delete-modal" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  edit: { color: colors.brandPrimary, fontSize: 15, fontWeight: "600" },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  tag: { fontSize: 11, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, fontWeight: "700", marginTop: spacing.sm, lineHeight: 36 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill },
  chipText: { fontSize: 12, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  progressBlock: { marginTop: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  progressText: { marginTop: 6 },
  progressBig: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, fontWeight: "700" },
  progressSmall: { fontSize: 13, color: colors.onSurfaceSecondary },
  progressBarTrack: { height: 6, backgroundColor: colors.surfaceTertiary, borderRadius: 3, marginTop: spacing.md, overflow: "hidden" },
  progressBarFill: { height: 6, backgroundColor: colors.brandPrimary },
  block: { marginTop: spacing.xl },
  notesText: { fontSize: 15, color: colors.onSurface, lineHeight: 22, marginTop: spacing.xs },
  section: { marginTop: spacing.xl },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  sectionLabel: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  emptyLine: { color: colors.onSurfaceTertiary, fontSize: 13, marginTop: spacing.xs },
  addStructureBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: 6 },
  addStructureText: { fontSize: 12, color: colors.onSurface, fontWeight: "500" },
  stageBlock: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  stageHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stageName: { fontFamily: fonts.displayBold, fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  stageActions: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  nodeRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, marginTop: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  chevBtn: { width: 20, alignItems: "center" },
  nodeTitleRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  nodeName: { fontSize: 14, color: colors.onSurface, fontWeight: "500", flexShrink: 1 },
  nodeType: { fontSize: 11, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  nodeMetaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 },
  nodeMeta: { fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  nodeActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  disabledIcon: { opacity: 0.3 },
  leafRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.sm },
  leafTitle: { fontSize: 14, color: colors.onSurface, fontWeight: "500" },
  leafMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  checkinDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary },
  planBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, backgroundColor: colors.brandPrimary,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg,
    borderRadius: radius.md, marginTop: spacing.lg,
  },
  planBtnText: { color: colors.onBrandPrimary, fontWeight: "600", fontSize: 14 },
});

const sheetStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(30,30,28,0.5)" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, gap: spacing.sm, maxHeight: "88%" },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.md },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: colors.onSurface, fontWeight: "600" },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, letterSpacing: 0.5 },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 15, color: colors.onSurface },
  notes: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontSize: 15, color: colors.onSurface, minHeight: 80 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  chipSel: { backgroundColor: colors.brandPrimary },
  chipText: { color: colors.onBrandTertiary, fontSize: 12, fontWeight: "500", textTransform: "capitalize" },
  chipTextSel: { color: colors.onBrandPrimary },
  err: { color: colors.error, fontSize: 13, marginTop: spacing.sm },
  cta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "600" },
});
