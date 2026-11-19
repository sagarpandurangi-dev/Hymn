import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, Text, TextInput, View } from "react-native";

import { ApiError, api } from "@/src/lib/api";
import { FAMILY_RELATIONS } from "@/src/lib/family";
import { lifeStyles as s } from "@/src/components/finance/lifeObjects";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

/** Bottom sheet for "Invite by Pamphlet ID" or "Add someone without the app". */
export default function FamilyMemberSheet({ mode, onClose, onDone }: { mode: "invite" | "add" | null; onClose: () => void; onDone: (msg: string) => void }) {
  const [text, setText] = useState("");
  const [relation, setRelation] = useState("spouse");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const close = () => { setText(""); setError(""); onClose(); };

  const submit = async () => {
    if (!text.trim()) { setError(mode === "invite" ? "Enter their Pamphlet ID." : "Enter a name."); return; }
    setBusy(true);
    setError("");
    try {
      if (mode === "invite") {
        await api.inviteToFamily(text.trim().toUpperCase(), relation);
        onDone("Invite sent. They'll see it in their Family screen.");
      } else {
        await api.addFamilyMember(text.trim(), relation);
        onDone("Added to your family.");
      }
      setText("");
    } catch (e) {
      const msg = (e as ApiError).message || "";
      setError(/at least 7|at most/.test(msg) ? "Pamphlet IDs are 7 characters, like L371621." : msg || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={!!mode} transparent animationType="slide" onRequestClose={close}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" }}>
        <Pressable style={{ flex: 1 }} onPress={close} />
        <View style={{ backgroundColor: financeColors.page, padding: financeSpace.xl, borderTopLeftRadius: 16, borderTopRightRadius: 16, gap: financeSpace.sm }} testID="family-member-sheet">
          <Text style={s.h}>{mode === "invite" ? "Invite by Pamphlet ID" : "Add someone without the app"}</Text>
          <Text style={s.label}>{mode === "invite" ? "Pamphlet ID" : "Name"}</Text>
          <TextInput
            style={s.input}
            value={text}
            onChangeText={(v) => { setText(v); setError(""); }}
            placeholder={mode === "invite" ? "e.g. L371621" : "e.g. Asha"}
            placeholderTextColor={financeColors.inkMuted}
            autoCapitalize={mode === "invite" ? "characters" : "words"}
            autoCorrect={false}
            testID="family-member-input"
          />
          <Text style={s.label}>Relation</Text>
          <View style={s.chipRow}>
            {FAMILY_RELATIONS.map((r) => {
              const on = r.code === relation;
              return (
                <Pressable key={r.code} style={[s.chip, on && s.chipOn]} onPress={() => setRelation(r.code)} testID={`family-relation-${r.code}`}>
                  <Text style={[s.chipText, on && s.chipTextOn]}>{r.label}</Text>
                </Pressable>
              );
            })}
          </View>
          {error ? <Text style={s.error} testID="family-member-error">{error}</Text> : null}
          <Pressable style={[s.primary, { marginTop: 12 }, busy && { opacity: 0.5 }]} onPress={submit} disabled={busy} testID="family-member-submit">
            {busy ? <ActivityIndicator color={financeColors.card} /> : <Text style={s.primaryText}>{mode === "invite" ? "Send invite" : "Add"}</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
