/** "Me" or one of the people I look after — sets whose Health data is shown. */
import { useCallback, useState } from "react";
import { Pressable, ScrollView, Text } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/lib/api";
import { hs } from "@/src/components/health/ui";
import { CarePerson, setHealthPerson, useHealthPerson } from "@/src/lib/healthPerson";
import { spacing } from "@/src/lib/theme";

export default function PersonSwitcher() {
  const person = useHealthPerson();
  const [people, setPeople] = useState<CarePerson[]>([]);

  useFocusEffect(useCallback(() => {
    api.listCare()
      .then((r) => {
        const list: CarePerson[] = (Array.isArray(r) ? r : []).map((p: any) => ({ id: p.id, name: p.name, relation: p.relation }));
        setPeople(list);
        // The chosen person may have been removed or renamed.
        const cur = list.find((p) => p.id === person?.id);
        if (person && !cur) setHealthPerson(null);
        else if (person && cur && cur.name !== person.name) setHealthPerson(cur);
      })
      .catch(() => setPeople([]));
  }, [person]));

  if (people.length === 0) return null;
  const chips = [{ id: "", name: "Me" }, ...people];
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, flexShrink: 0 }} contentContainerStyle={{ gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, alignItems: "center" }} testID="health-person-switcher">
      {chips.map((p) => {
        const on = (person?.id ?? "") === p.id;
        return (
          <Pressable key={p.id || "me"} style={[hs.chip, on && hs.chipOn]} onPress={() => setHealthPerson(p.id ? (p as CarePerson) : null)} testID={`health-person-${p.id || "me"}`}>
            <Text style={[hs.chipText, on && hs.chipTextOn]}>{p.name}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
