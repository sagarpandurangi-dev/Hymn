import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import HealthProfileForm from "@/src/components/health/HealthProfileForm";
import { HealthHeader, hs } from "@/src/components/health/ui";
import { showToast } from "@/src/lib/toast";
import { useHealthPerson } from "@/src/lib/healthPerson";
import { colors, spacing } from "@/src/lib/theme";

export default function HealthSettingsScreen() {
  const router = useRouter();
  const person = useHealthPerson();
  const [profile, setProfile] = useState<any>(null);
  const [options, setOptions] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.getHealthProfile(), api.getHealthOptions().catch(() => null)])
      .then(([p, o]) => { setProfile(p); setOptions(o); })
      .catch((e: ApiError) => setError(e.message || "Couldn't load the profile."));
  }, [person]);

  return (
    <SafeAreaView style={hs.safe} edges={["top", "bottom"]} testID="health-settings-screen">
      <HealthHeader title="Health settings" testID="health-settings" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={hs.scroll} keyboardShouldPersistTaps="handled">
          {!profile ? (error ? <Text style={hs.error}>{error}</Text> : <ActivityIndicator color={colors.onSurfaceTertiary} />) : (
            <>
              <View>
                <Text style={hs.h}>{person ? `${person.name}'s profile` : "Your profile"}</Text>
                <HealthProfileForm key={person?.id ?? "me"} initial={profile} options={options} forOther={!!person} saveLabel="Save changes" onSaved={(p) => { setProfile(p); showToast("Profile saved."); }} />
              </View>
              {!person ? (
                <Pressable style={[hs.secondary, { borderColor: colors.error, marginTop: spacing.lg }]} onPress={() => router.push("/life/health/delete" as any)} testID="health-open-delete">
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                  <Text style={[hs.secondaryText, { color: colors.error }]}>Delete all my health data</Text>
                </Pressable>
              ) : null}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
