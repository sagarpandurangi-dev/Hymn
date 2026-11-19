import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { CIRCLES, PEOPLE_RELATIONS } from "@/src/lib/people";
import { colors, spacing } from "@/src/lib/theme";

type Occ = { label: string; day: string; month: string; gift: string };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const num = (v: string) => v.replace(/[^0-9]/g, "");
const pad = (v: string) => v.padStart(2, "0");
/** "YYYY-MM-DD" or "MM-DD" → parts. */
const split = (s?: string | null) => {
  if (!s) return { y: "", m: "", d: "" };
  const p = s.split("-");
  return p.length === 3 ? { y: p[0], m: String(Number(p[1])), d: String(Number(p[2])) } : { y: "", m: String(Number(p[0])), d: String(Number(p[1])) };
};
const join = (y: string, m: string, d: string) => (m && d ? (y ? `${y}-${pad(m)}-${pad(d)}` : `${pad(m)}-${pad(d)}`) : null);

function Chips({ options, value, onChange, testPrefix }: { options: { code: string; label: string }[]; value: string; onChange: (v: string) => void; testPrefix: string }) {
  return (
    <View style={hs.chipRow}>
      {options.map((o) => (
        <Pressable key={o.code} style={[hs.chip, value === o.code && hs.chipOn]} onPress={() => onChange(o.code)} testID={`${testPrefix}-${o.code}`}>
          <Text style={[hs.chipText, value === o.code && hs.chipTextOn]}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function DayMonth({ day, month, onDay, onMonth, testID }: { day: string; month: string; onDay: (v: string) => void; onMonth: (v: string) => void; testID: string }) {
  return (
    <View style={{ gap: spacing.sm }}>
      <TextInput style={[hs.input, { width: 90 }]} value={day} onChangeText={(v) => onDay(num(v).slice(0, 2))} keyboardType="number-pad" placeholder="Day" placeholderTextColor={colors.onSurfaceTertiary} testID={`${testID}-day`} />
      <View style={hs.chipRow}>
        {MONTHS.map((m, i) => (
          <Pressable key={m} style={[hs.chip, { minHeight: 34, paddingHorizontal: 10 }, month === String(i + 1) && hs.chipOn]} onPress={() => onMonth(String(i + 1))} testID={`${testID}-month-${i + 1}`}>
            <Text style={[hs.chipText, { fontSize: 13 }, month === String(i + 1) && hs.chipTextOn]}>{m}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export default function EditPersonScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(!!id);
  const [name, setName] = useState("");
  const [relation, setRelation] = useState("friend");
  const [circle, setCircle] = useState("close");
  const [bd, setBd] = useState({ y: "", m: "", d: "" });
  const [gift, setGift] = useState("");
  const [occasions, setOccasions] = useState<Occ[]>([]);
  const [keep, setKeep] = useState("0");
  const [notes, setNotes] = useState("");
  const [careId, setCareId] = useState<string>("");
  const [care, setCare] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listCare().then((r) => setCare(Array.isArray(r) ? r : [])).catch(() => setCare([]));
    if (!id) return;
    api.getPerson(String(id)).then((p) => {
      setName(p.name ?? ""); setRelation(p.relation ?? "friend"); setCircle(p.circle ?? "close");
      setBd(split(p.birthday)); setGift(p.birthday_gift != null ? String(p.birthday_gift) : "");
      setOccasions((p.occasions ?? []).map((o: any) => { const s = split(o.date); return { label: o.label ?? "", day: s.d, month: s.m, gift: o.gift_budget != null ? String(o.gift_budget) : "" }; }));
      setKeep(String(p.keep_in_touch_days ?? 0)); setNotes(p.notes ?? ""); setCareId(p.care_id ?? "");
    }).catch((e: ApiError) => setError(e.message || "Couldn't load.")).finally(() => setLoading(false));
  }, [id]);

  const save = async () => {
    setError("");
    if (!name.trim()) { setError("Add their name."); return; }
    if ((bd.d || bd.m) && !(bd.d && bd.m)) { setError("For the birthday, add both the day and the month."); return; }
    const occ = occasions.filter((o) => o.label.trim() || o.day || o.month);
    if (occ.some((o) => !o.label.trim() || !o.day || !o.month)) { setError("Each other day needs a name, a day and a month."); return; }
    const payload: Record<string, any> = {
      name: name.trim(), relation, circle,
      birthday: join(bd.y, bd.m, bd.d),
      birthday_gift: gift ? Number(gift) : null,
      occasions: occ.map((o) => ({ label: o.label.trim(), date: join("", o.month, o.day), gift_budget: o.gift ? Number(o.gift) : null })),
      keep_in_touch_days: Number(keep || 0),
      notes: notes.trim() || null,
      care_id: careId || null,
    };
    setBusy(true);
    try {
      const res = id ? await api.updatePerson(String(id), payload) : await api.createPerson(payload);
      if (!id && res?.id) router.replace(`/life/family/${res.id}` as any);
      else if (router.canGoBack()) router.back();
      else router.replace("/life/family" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const remove = () => {
    const run = async () => {
      try {
        await api.deletePerson(String(id));
        router.replace("/life/family" as any);
      } catch (e) {
        setError((e as ApiError).message || "Couldn't delete. Try again.");
      }
    };
    const body = `Remove ${name} and the moments logged only with them?`;
    if (Platform.OS === "web") { if (window.confirm(body)) run(); return; }
    Alert.alert("Remove person", body, [{ text: "Cancel", style: "cancel" }, { text: "Remove", style: "destructive", onPress: run }]);
  };

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="person-edit-screen">
      <HealthHeader title={id ? "Edit person" : "Add someone"} testID="person-edit" hidePerson />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          {loading ? <ActivityIndicator color={colors.onSurfaceTertiary} /> : (
            <View>
              <Text style={hs.label}>Name</Text>
              <TextInput style={hs.input} value={name} onChangeText={setName} placeholder="e.g. Amma" placeholderTextColor={colors.onSurfaceTertiary} testID="person-name" />
              <Text style={hs.label}>They are my</Text>
              <Chips options={PEOPLE_RELATIONS} value={relation} onChange={setRelation} testPrefix="person-relation" />
              <Text style={hs.label}>Circle</Text>
              <Chips options={CIRCLES} value={circle} onChange={setCircle} testPrefix="person-circle" />

              <Text style={hs.label}>Birthday (optional)</Text>
              <DayMonth day={bd.d} month={bd.m} onDay={(d) => setBd({ ...bd, d })} onMonth={(m) => setBd({ ...bd, m })} testID="person-bd" />
              <TextInput style={[hs.input, { width: 140, marginTop: spacing.sm }]} value={bd.y} onChangeText={(v) => setBd({ ...bd, y: num(v).slice(0, 4) })} keyboardType="number-pad" placeholder="Year (optional)" placeholderTextColor={colors.onSurfaceTertiary} testID="person-bd-year" />
              <Text style={hs.label}>Birthday gift budget (₹, optional)</Text>
              <TextInput style={hs.input} value={gift} onChangeText={(v) => setGift(num(v))} keyboardType="number-pad" placeholder="e.g. 2000" placeholderTextColor={colors.onSurfaceTertiary} testID="person-bd-gift" />

              <Text style={hs.label}>Other days that matter</Text>
              {occasions.map((o, i) => (
                <View key={i} style={[hs.card, { marginBottom: spacing.sm }]} testID={`person-occasion-${i}`}>
                  <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
                    <TextInput style={[hs.input, { flex: 1 }]} value={o.label} onChangeText={(v) => setOccasions(occasions.map((x, j) => (j === i ? { ...x, label: v } : x)))} placeholder="e.g. Anniversary" placeholderTextColor={colors.onSurfaceTertiary} testID={`person-occasion-label-${i}`} />
                    <Pressable onPress={() => setOccasions(occasions.filter((_, j) => j !== i))} hitSlop={8} testID={`person-occasion-remove-${i}`}><Ionicons name="close" size={20} color={colors.onSurfaceSecondary} /></Pressable>
                  </View>
                  <DayMonth day={o.day} month={o.month} onDay={(v) => setOccasions(occasions.map((x, j) => (j === i ? { ...x, day: v } : x)))} onMonth={(v) => setOccasions(occasions.map((x, j) => (j === i ? { ...x, month: v } : x)))} testID={`person-occasion-${i}`} />
                  <TextInput style={hs.input} value={o.gift} onChangeText={(v) => setOccasions(occasions.map((x, j) => (j === i ? { ...x, gift: num(v) } : x)))} keyboardType="number-pad" placeholder="Gift budget ₹ (optional)" placeholderTextColor={colors.onSurfaceTertiary} testID={`person-occasion-gift-${i}`} />
                </View>
              ))}
              <Pressable style={[hs.chip, { alignSelf: "flex-start" }]} onPress={() => setOccasions([...occasions, { label: "", day: "", month: "", gift: "" }])} testID="person-add-occasion">
                <Text style={hs.chipText}>+ Add a day</Text>
              </Pressable>

              <Text style={hs.label}>Keep in touch every … days</Text>
              <TextInput style={[hs.input, { width: 120 }]} value={keep} onChangeText={(v) => setKeep(num(v))} keyboardType="number-pad" placeholder="0" placeholderTextColor={colors.onSurfaceTertiary} testID="person-keep" />
              <Text style={hs.muted}>0 means no gentle nudge.</Text>

              <Text style={hs.label}>Private notes</Text>
              <TextInput style={[hs.input, { minHeight: 80, paddingTop: 12, textAlignVertical: "top" }]} value={notes} onChangeText={setNotes} multiline placeholder="Likes, sizes, things to remember" placeholderTextColor={colors.onSurfaceTertiary} testID="person-notes" />

              {care.length > 0 ? (
                <>
                  <Text style={hs.label}>Someone I look after? (optional)</Text>
                  <Chips options={[{ code: "", label: "No" }, ...care.map((c) => ({ code: c.id, label: c.name }))]} value={careId} onChange={setCareId} testPrefix="person-care" />
                </>
              ) : null}

              {error ? <Text style={[hs.error, { marginTop: spacing.md }]} testID="person-edit-error">{error}</Text> : null}
              <Pressable style={[hs.primary, { marginTop: spacing.xl }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="person-save">
                {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={hs.primaryText}>Save</Text>}
              </Pressable>
              {id ? (
                <Pressable style={{ minHeight: 48, alignItems: "center", justifyContent: "center" }} onPress={remove} testID="person-delete">
                  <Text style={[hs.body, { color: colors.error, fontWeight: "600" }]}>Remove this person</Text>
                </Pressable>
              ) : null}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
