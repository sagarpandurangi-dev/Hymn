import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { foldPageStyle } from "@/src/components/finance/foldUi";
import { lifeStyles as s } from "@/src/components/finance/lifeObjects";
import { ASSET_GROUPS, LIABILITY_GROUPS, loadFamilyItems, relationLabel, saveFamilyItems } from "@/src/lib/family";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

type Opt = { code: string; label: string };
function Chips({ options, value, onChange, testPrefix }: { options: Opt[]; value: string; onChange: (v: string) => void; testPrefix: string }) {
  return (
    <View style={s.chipRow}>
      {options.map((o) => {
        const on = o.code === value;
        return (
          <Pressable key={o.code} style={[s.chip, on && s.chipOn]} onPress={() => onChange(o.code)} testID={`${testPrefix}-${o.code}`}>
            <Text style={[s.chipText, on && s.chipTextOn]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function AddFamilyItemScreen() {
  const router = useRouter();
  const [familyId, setFamilyId] = useState("");
  const [members, setMembers] = useState<any[]>([]);
  const [side, setSide] = useState<"asset" | "liability">("asset");
  const [group, setGroup] = useState("fixed");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [pct, setPct] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getFamily().then((d) => {
      setFamilyId(d?.family?.id ?? "");
      // Only people already in the family can own things (not pending invites).
      setMembers((d?.members ?? []).filter((m: any) => m.status !== "invited"));
    }).catch((e: ApiError) => setError(e.message || "Couldn't load your family."));
  }, []);

  const groups = side === "asset" ? ASSET_GROUPS : LIABILITY_GROUPS;
  const owners = Object.entries(pct).filter(([, v]) => v !== "");
  const total = owners.reduce((t, [, v]) => t + Number(v || 0), 0);

  const toggleOwner = (id: string) => {
    const next = { ...pct };
    if (next[id] !== undefined) delete next[id];
    else next[id] = "";
    // Split evenly as a starting point; the person can change each %.
    const ids = Object.keys(next);
    if (ids.length > 0) {
      const each = Math.floor(100 / ids.length);
      ids.forEach((k, i) => { next[k] = String(i === 0 ? 100 - each * (ids.length - 1) : each); });
    }
    setPct(next);
  };

  const save = async () => {
    setError("");
    if (!name.trim()) { setError("Give it a name."); return; }
    if (!amount || Number(amount) <= 0) { setError("Enter an amount."); return; }
    if (owners.length === 0) { setError("Pick who owns it."); return; }
    if (Math.abs(total - 100) > 0.001) { setError(`Owner shares must add up to 100% (now ${total}%).`); return; }
    const shares: Record<string, number> = {};
    owners.forEach(([id, v]) => { shares[id] = Number(v); });
    setBusy(true);
    try {
      const created = await api.addFamilyItem({ side, group, name: name.trim(), amount, shares });
      if (familyId && created?.id) {
        const list = await loadFamilyItems(familyId);
        await saveFamilyItems(familyId, [...list, { id: created.id, side, group, name: created.name ?? name.trim(), amount: created.amount ?? amount, shares: created.shares ?? shares }]);
      }
      if (router.canGoBack()) router.back();
      else router.replace("/finance/family" as any);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Add an entry" subtitle="For one person or owned jointly" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <View>
            <Text style={s.label}>Side</Text>
            <Chips options={[{ code: "asset", label: "Asset" }, { code: "liability", label: "Liability" }]} value={side} onChange={(v) => { setSide(v as any); setGroup(v === "asset" ? "fixed" : "loans"); }} testPrefix="family-item-side" />
            <Text style={s.label}>Group</Text>
            <Chips options={groups} value={group} onChange={setGroup} testPrefix="family-item-group" />
            <Text style={s.label}>Name</Text>
            <TextInput style={s.input} value={name} onChangeText={setName} placeholder={side === "asset" ? "e.g. Flat in Pune" : "e.g. Home loan"} placeholderTextColor={financeColors.inkMuted} testID="family-item-name" />
            <Text style={s.label}>Amount (₹)</Text>
            <TextInput style={s.input} value={amount} onChangeText={(v) => setAmount(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={financeColors.inkMuted} testID="family-item-amount" />

            <Text style={s.label}>Who owns it</Text>
            <View style={s.chipRow}>
              {members.map((m) => {
                const on = pct[m.id] !== undefined;
                return (
                  <Pressable key={m.id} style={[s.chip, on && s.chipOn]} onPress={() => toggleOwner(m.id)} testID={`family-item-owner-${m.id}`}>
                    <Text style={[s.chipText, on && s.chipTextOn]}>{m.relation === "self" ? m.name : `${m.name} · ${relationLabel(m.relation)}`}</Text>
                  </Pressable>
                );
              })}
            </View>
            {owners.length > 0 ? (
              <View style={{ gap: financeSpace.sm, marginTop: financeSpace.md }}>
                {Object.keys(pct).map((id) => (
                  <View key={id} style={{ flexDirection: "row", alignItems: "center", gap: financeSpace.md }}>
                    <Text style={[s.body, { flex: 1, color: financeColors.ink }]} numberOfLines={1}>{members.find((m) => m.id === id)?.name}</Text>
                    <TextInput
                      style={[s.input, { width: 90, textAlign: "right" }]}
                      value={pct[id]}
                      onChangeText={(v) => setPct({ ...pct, [id]: v.replace(/[^0-9.]/g, "") })}
                      keyboardType="decimal-pad"
                      testID={`family-item-pct-${id}`}
                    />
                    <Text style={s.body}>%</Text>
                  </View>
                ))}
                <Text style={[s.body, Math.abs(total - 100) > 0.001 && { color: financeColors.negative }]} testID="family-item-pct-total">Total {total}% {Math.abs(total - 100) > 0.001 ? "— must be 100%" : ""}</Text>
              </View>
            ) : null}

            {error ? <Text style={[s.error, { marginTop: 12 }]} testID="family-item-error">{error}</Text> : null}
            <Pressable style={[s.primary, { marginTop: 20 }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="family-item-save">
              {busy ? <ActivityIndicator color={financeColors.card} /> : <Text style={s.primaryText}>Save</Text>}
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
