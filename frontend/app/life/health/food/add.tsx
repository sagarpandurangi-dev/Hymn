import { useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import * as ImagePicker from "expo-image-picker";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { AmountStepper, FoodSearch, MEALS } from "@/src/components/food/FoodBits";
import { pickImage, takePhoto, PickedFile } from "@/src/utils/upload";
import { colors, radius, spacing } from "@/src/lib/theme";

type Item = { key: string; food?: any; amount: number; name?: string; seen_as?: string; confidence?: string; alternatives?: any[]; photo?: boolean };

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const defaultMeal = () => { const h = new Date().getHours(); return h < 11 ? "breakfast" : h < 16 ? "lunch" : h < 22 ? "dinner" : "snack"; };
let seq = 0;
const newKey = () => `i${Date.now()}${seq++}`;

export default function AddMealScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ date?: string }>();
  const date = params.date || iso(new Date());
  const [meal, setMeal] = useState(defaultMeal());
  const [outside, setOutside] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [searchFor, setSearchFor] = useState<string | "new" | null>(null); // item key to replace, or "new"
  const [changeFor, setChangeFor] = useState<Item | null>(null);
  const [other, setOther] = useState("");
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoMsg, setPhotoMsg] = useState("");
  const [photoNote, setPhotoNote] = useState("");
  const [photosLeft, setPhotosLeft] = useState<number | null>(null);
  const [cameraBlocked, setCameraBlocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const update = (key: string, patch: Partial<Item>) => setItems((l) => l.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  const remove = (key: string) => setItems((l) => l.filter((x) => x.key !== key));

  const onPicked = (food: any) => {
    if (searchFor && searchFor !== "new") update(searchFor, { food, confidence: undefined });
    else setItems((l) => [...l, { key: newKey(), food, amount: 1 }]);
    setSearchFor(null);
  };

  const addOther = () => {
    const n = other.trim();
    if (!n) return;
    setItems((l) => [...l, { key: newKey(), name: n, amount: 1 }]);
    setOther("");
  };

  const readPhoto = async (file: PickedFile | null) => {
    if (!file) return;
    setPhotoBusy(true);
    setPhotoMsg("");
    setPhotoNote("");
    try {
      const res = await api.readFoodPhoto(file.base64, file.mediaType);
      if (res?.photos_left != null) setPhotosLeft(res.photos_left);
      if (res?.kind === "not_food") setPhotoMsg("That doesn't look like food.");
      else if (res?.kind === "label") {
        router.push({ pathname: "/life/health/food/my-foods", params: { prefill: JSON.stringify(res.label ?? {}) } } as any);
      } else {
        const got: Item[] = (res?.items ?? []).map((x: any) => ({ key: newKey(), food: x.food ?? undefined, amount: Number(x.amount) || 1, seen_as: x.seen_as, confidence: x.confidence, alternatives: x.alternatives ?? [], photo: true }));
        if (got.length === 0) setPhotoMsg("Couldn't spot any food — search instead.");
        setItems((l) => [...l, ...got]);
        if (res?.note) setPhotoNote(res.note);
      }
    } catch (e) {
      const err = e as ApiError;
      setPhotoMsg(err.status === 503 ? "Couldn't read the photo — search instead." : err.message || "Couldn't read the photo — search instead.");
    } finally {
      setPhotoBusy(false);
    }
  };

  /** Camera permission: check, explain once, ask, and offer Settings if blocked. */
  const openCamera = async () => {
    if (Platform.OS === "web") { readPhoto(await pickImage()); return; }
    const cur = await ImagePicker.getCameraPermissionsAsync();
    if (cur.granted) { readPhoto(await takePhoto()); return; }
    if (!cur.canAskAgain) { setCameraBlocked(true); return; }
    Alert.alert("Use your camera?", "Snap your plate and Hymn lists what it sees, so logging takes seconds.", [
      { text: "Not now", style: "cancel" },
      {
        text: "Continue",
        onPress: async () => {
          const r = await ImagePicker.requestCameraPermissionsAsync();
          if (r.granted) { setCameraBlocked(false); readPhoto(await takePhoto()); }
          else if (!r.canAskAgain) setCameraBlocked(true);
        },
      },
    ]);
  };

  const save = async () => {
    setError("");
    if (items.length === 0) { setError("Add at least one thing you ate."); return; }
    const unmatched = items.filter((i) => !i.food && !i.name);
    if (unmatched.length) { setError("Pick a food for each line marked “Not sure”, or remove it."); return; }
    setBusy(true);
    try {
      await api.saveMeal({
        date,
        meal,
        outside,
        from_photo: items.some((i) => i.photo),
        items: items.map((i) => (i.food ? { food_id: i.food.id, amount: i.amount } : { name: i.name! })),
      });
      if (router.canGoBack()) router.back(); else router.replace("/life/health/food" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="food-add-screen">
      <HealthHeader title="Add a meal" testID="food-add" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          <View style={hs.chipRow}>
            {MEALS.map((m) => (
              <Pressable key={m.code} style={[hs.chip, meal === m.code && hs.chipOn]} onPress={() => setMeal(m.code)} testID={`food-meal-${m.code}`}>
                <Text style={[hs.chipText, meal === m.code && hs.chipTextOn]}>{m.label}</Text>
              </Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48 }}>
            <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>Eaten out / ordered in</Text>
            <Switch value={outside} onValueChange={setOutside} testID="food-outside-switch" />
          </View>

          {items.length > 0 ? (
            <View style={hs.card} testID="food-items">
              {photoNote ? <Text style={hs.muted}>{photoNote}</Text> : null}
              {items.map((it) => (
                <View key={it.key} style={{ gap: 6, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider }} testID={`food-item-${it.key}`}>
                  {it.seen_as ? <Text style={hs.muted}>Seen as: {it.seen_as}</Text> : null}
                  <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      {it.food ? (
                        <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>
                          {it.food.name}{it.confidence === "low" ? <Text style={{ color: colors.warning }}>  ?</Text> : null}
                        </Text>
                      ) : it.name ? (
                        <Text style={[hs.body, { color: colors.onSurface, fontWeight: "600" }]}>{it.name} <Text style={hs.muted}>· saved, not counted</Text></Text>
                      ) : (
                        <Pressable onPress={() => setSearchFor(it.key)} testID={`food-item-unsure-${it.key}`}>
                          <Text style={[hs.body, { color: colors.brandPrimary, fontWeight: "600" }]}>Not sure — search</Text>
                        </Pressable>
                      )}
                      {it.food ? <Text style={hs.muted}>{it.food.unit}</Text> : null}
                    </View>
                    {it.food ? <AmountStepper value={it.amount} onChange={(v) => update(it.key, { amount: v })} testID={`food-item-amount-${it.key}`} /> : null}
                  </View>
                  <View style={{ flexDirection: "row", gap: spacing.md }}>
                    {it.photo && it.food ? (
                      <Pressable onPress={() => setChangeFor(it)} hitSlop={6} testID={`food-item-change-${it.key}`}><Text style={[hs.muted, { color: colors.brandPrimary, fontWeight: "600" }]}>Change</Text></Pressable>
                    ) : null}
                    <Pressable onPress={() => remove(it.key)} hitSlop={6} testID={`food-item-remove-${it.key}`}><Text style={[hs.muted, { fontWeight: "600" }]}>Remove</Text></Pressable>
                  </View>
                </View>
              ))}
            </View>
          ) : null}

          <View style={{ gap: spacing.sm }}>
            <Text style={hs.section}>ADD WHAT YOU ATE</Text>
            <Pressable style={hs.secondary} onPress={() => setSearchFor("new")} testID="food-open-search">
              <Ionicons name="search" size={18} color={colors.onSurface} />
              <Text style={hs.secondaryText}>Search</Text>
            </Pressable>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable style={[hs.secondary, { flex: 1 }, photoBusy && { opacity: 0.5 }]} onPress={openCamera} disabled={photoBusy} testID="food-take-photo">
                <Ionicons name="camera-outline" size={18} color={colors.onSurface} />
                <Text style={hs.secondaryText}>Take photo</Text>
              </Pressable>
              <Pressable style={[hs.secondary, { flex: 1 }, photoBusy && { opacity: 0.5 }]} onPress={async () => readPhoto(await pickImage())} disabled={photoBusy} testID="food-pick-photo">
                <Ionicons name="image-outline" size={18} color={colors.onSurface} />
                <Text style={hs.secondaryText}>Pick photo</Text>
              </Pressable>
            </View>
            {photoBusy ? <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}><ActivityIndicator color={colors.onSurfaceTertiary} /><Text style={hs.muted}>Looking at your photo…</Text></View> : null}
            {photoMsg ? <Text style={[hs.body, { color: colors.onSurface }]} testID="food-photo-message">{photoMsg}</Text> : null}
            {photosLeft != null ? <Text style={hs.muted} testID="food-photos-left">{photosLeft} photos left</Text> : null}
            {cameraBlocked ? (
              <View style={{ gap: spacing.xs }}>
                <Text style={hs.muted}>Camera access is off for Hymn. You can turn it on in Settings, or pick a photo instead.</Text>
                <Pressable style={[hs.chip, { alignSelf: "flex-start" }]} onPress={() => Linking.openSettings()} testID="food-open-settings">
                  <Text style={hs.chipText}>Open Settings</Text>
                </Pressable>
              </View>
            ) : null}

            <Text style={hs.label}>Something else</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <TextInput style={[hs.input, { flex: 1 }]} value={other} onChangeText={setOther} placeholder="e.g. Aunty's special halwa" placeholderTextColor={colors.onSurfaceTertiary} onSubmitEditing={addOther} returnKeyType="done" testID="food-other-input" />
              <Pressable style={[hs.secondary, { paddingHorizontal: spacing.lg }]} onPress={addOther} testID="food-other-add"><Text style={hs.secondaryText}>Add</Text></Pressable>
            </View>
            <Text style={hs.muted}>Saved with the meal but not counted in the totals.</Text>
          </View>

          {error ? <Text style={hs.error} testID="food-add-error">{error}</Text> : null}
          <Pressable style={[hs.primary, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="food-save-meal">
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save meal</Text>}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal visible={!!searchFor} animationType="slide" onRequestClose={() => setSearchFor(null)}>
        <SafeAreaView style={hs.safe} edges={["top", "bottom"]}>
          <View style={hs.header}>
            <Pressable onPress={() => setSearchFor(null)} style={hs.iconBtn} testID="food-search-close"><Ionicons name="close" size={24} color={colors.onSurface} /></Pressable>
            <Text style={hs.title}>Find a food</Text>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.lg }} keyboardShouldPersistTaps="handled">
            <FoodSearch onPick={onPicked} autoFocus initialQuery={searchFor && searchFor !== "new" ? items.find((i) => i.key === searchFor)?.seen_as ?? "" : ""} />
          </ScrollView>
        </SafeAreaView>
      </Modal>

      <Modal visible={!!changeFor} transparent animationType="slide" onRequestClose={() => setChangeFor(null)}>
        <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" }}>
          <Pressable style={{ flex: 1 }} onPress={() => setChangeFor(null)} />
          <View style={{ backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, gap: spacing.sm }} testID="food-change-sheet">
            <Text style={hs.h}>Change “{changeFor?.food?.name}”</Text>
            {(changeFor?.alternatives ?? []).map((f: any) => (
              <Pressable key={f.id} style={[hs.secondary, { justifyContent: "flex-start", paddingHorizontal: spacing.lg }]} onPress={() => { update(changeFor!.key, { food: f, confidence: undefined }); setChangeFor(null); }} testID={`food-alt-${f.id}`}>
                <Text style={hs.secondaryText}>{f.name}</Text>
                <Text style={hs.muted}>1 {f.unit}</Text>
              </Pressable>
            ))}
            <Pressable style={hs.primary} onPress={() => { const k = changeFor!.key; setChangeFor(null); setSearchFor(k); }} testID="food-change-search">
              <Text style={hs.primaryText}>Search instead</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
