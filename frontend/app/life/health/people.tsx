import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs, niceDay } from "@/src/components/health/ui";
import { CARE_RELATIONS, careRelationLabel, getHealthPerson, setHealthPerson } from "@/src/lib/healthPerson";
import { colors, radius, spacing } from "@/src/lib/theme";

const confirmRemove = (name: string, ok: () => void) => {
  const body = `Remove ${name}? This deletes all their health data.`;
  if (Platform.OS === "web") { if (window.confirm(body)) ok(); return; }
  Alert.alert("Remove person", body, [{ text: "Cancel", style: "cancel" }, { text: "Remove", style: "destructive", onPress: ok }]);
};

export default function PeopleScreen() {
  const router = useRouter();
  const [people, setPeople] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [relation, setRelation] = useState("mother");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<any>(null);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.listCare();
      setPeople(Array.isArray(r) ? r : []);
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load the people you look after.");
      setPeople([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const add = async () => {
    setError("");
    if (!name.trim()) { setError("Add their name."); return; }
    if (!agreed) { setError("Please confirm they know and agree, or that you're their guardian."); return; }
    setBusy(true);
    try {
      await api.addCare({ name: name.trim(), relation, their_consent: true });
      setName(""); setAgreed(false); setAdding(false);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't add them. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const rename = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await api.renameCare(renaming.id, newName.trim());
      if (getHealthPerson()?.id === renaming.id) setHealthPerson({ ...getHealthPerson()!, name: newName.trim() });
      setRenaming(null);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't rename. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const remove = (p: any) => confirmRemove(p.name, async () => {
    try {
      await api.deleteCare(p.id);
      if (getHealthPerson()?.id === p.id) setHealthPerson(null);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't remove. Try again.");
    }
  });

  const open = (p: any) => {
    setHealthPerson({ id: p.id, name: p.name, relation: p.relation });
    router.replace("/life/health" as any);
  };

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="people-screen">
      <HealthHeader title="People I look after" testID="people" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <Text style={hs.body}>Keep track of a parent&apos;s or child&apos;s check-ups and readings. Their data stays separate from yours.</Text>
          {error ? <Text style={hs.error} testID="people-error">{error}</Text> : null}

          {people === null ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : people.map((p) => (
            <View key={p.id} style={hs.card} testID={`care-${p.id}`}>
              <Pressable style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 }} onPress={() => open(p)} testID={`care-open-${p.id}`}>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                    <Text style={[hs.h, { fontSize: 16 }]}>{p.name}</Text>
                    {Number(p.checkups_due) > 0 ? <View style={[hs.dot, { backgroundColor: colors.warning }]} testID={`care-due-dot-${p.id}`} /> : null}
                  </View>
                  <Text style={hs.muted}>
                    {[careRelationLabel(p.relation), Number(p.checkups_due) > 0 ? `${p.checkups_due} check-up${p.checkups_due === 1 ? "" : "s"} due` : "", !p.profile_done ? "Profile to fill in" : ""].filter(Boolean).join(" · ")}
                  </Text>
                  {p.last_reading ? (
                    <Text style={hs.muted}>Last: {p.last_reading.label ?? p.last_reading.metric} {p.last_reading.value} {p.last_reading.unit ?? ""}{p.last_reading.date ? ` · ${niceDay(p.last_reading.date)}` : ""}</Text>
                  ) : null}
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
              </Pressable>
              <View style={{ flexDirection: "row", gap: spacing.lg }}>
                <Pressable onPress={() => { setRenaming(p); setNewName(p.name); }} hitSlop={8} testID={`care-rename-${p.id}`}><Text style={[hs.muted, { color: colors.brandPrimary, fontWeight: "600" }]}>Rename</Text></Pressable>
                <Pressable onPress={() => remove(p)} hitSlop={8} testID={`care-remove-${p.id}`}><Text style={[hs.muted, { color: colors.error, fontWeight: "600" }]}>Remove</Text></Pressable>
              </View>
            </View>
          ))}

          {adding ? (
            <View style={hs.card} testID="care-add-form">
              <Text style={hs.h}>Add someone</Text>
              <Text style={hs.label}>Name</Text>
              <TextInput style={hs.input} value={name} onChangeText={setName} placeholder="e.g. Amma" placeholderTextColor={colors.onSurfaceTertiary} testID="care-name" />
              <Text style={hs.label}>They are my</Text>
              <View style={hs.chipRow}>
                {CARE_RELATIONS.map((r) => (
                  <Pressable key={r.code} style={[hs.chip, relation === r.code && hs.chipOn]} onPress={() => setRelation(r.code)} testID={`care-relation-${r.code}`}>
                    <Text style={[hs.chipText, relation === r.code && hs.chipTextOn]}>{r.label}</Text>
                  </Pressable>
                ))}
              </View>
              <Pressable style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, marginTop: spacing.sm }} onPress={() => setAgreed(!agreed)} accessibilityRole="checkbox" accessibilityState={{ checked: agreed }} testID="care-consent">
                <Ionicons name={agreed ? "checkbox" : "square-outline"} size={24} color={agreed ? colors.brandPrimary : colors.onSurfaceSecondary} />
                <Text style={[hs.body, { flex: 1, color: colors.onSurface, fontWeight: "600" }]}>They know and agree, or I&apos;m their guardian</Text>
              </Pressable>
              <Pressable style={[hs.primary, (!agreed || busy) && { opacity: 0.5 }]} onPress={add} disabled={!agreed || busy} testID="care-save">
                {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Add</Text>}
              </Pressable>
              <Pressable style={{ minHeight: 44, alignItems: "center", justifyContent: "center" }} onPress={() => setAdding(false)} testID="care-cancel"><Text style={hs.body}>Cancel</Text></Pressable>
            </View>
          ) : (
            <Pressable style={hs.secondary} onPress={() => setAdding(true)} testID="care-add">
              <Ionicons name="person-add-outline" size={18} color={colors.onSurface} />
              <Text style={hs.secondaryText}>Add someone</Text>
            </Pressable>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal visible={!!renaming} transparent animationType="slide" onRequestClose={() => setRenaming(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" }}>
          <Pressable style={{ flex: 1 }} onPress={() => setRenaming(null)} />
          <View style={{ backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, gap: spacing.md }} testID="care-rename-sheet">
            <Text style={hs.h}>Rename</Text>
            <TextInput style={hs.input} value={newName} onChangeText={setNewName} autoFocus testID="care-rename-input" />
            <Pressable style={[hs.primary, busy && { opacity: 0.5 }]} onPress={rename} disabled={busy} testID="care-rename-save">
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}
