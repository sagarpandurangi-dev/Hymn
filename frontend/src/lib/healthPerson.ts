/**
 * Whose health is on screen: "Me" (null) or one of the people I look after.
 * Health API calls add ?for=<id> while someone else is chosen.
 */
import { useSyncExternalStore } from "react";

export type CarePerson = { id: string; name: string; relation?: string };

let current: CarePerson | null = null;
const listeners = new Set<() => void>();

export const getHealthPerson = () => current;
export const setHealthPerson = (p: CarePerson | null) => {
  current = p;
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => { listeners.delete(l); };
};

export function useHealthPerson(): CarePerson | null {
  return useSyncExternalStore(subscribe, getHealthPerson, getHealthPerson);
}

/** Adds ?for=<id> (or &for=) to a Health path when a cared-for person is chosen. */
export const forPerson = (path: string) => {
  if (!current) return path;
  return `${path}${path.includes("?") ? "&" : "?"}for=${encodeURIComponent(current.id)}`;
};

/** "Amma's health" / "Your health". */
export const whose = (p: CarePerson | null, what: string) => (p ? `${p.name}'s ${what}` : what.charAt(0).toUpperCase() + what.slice(1));

export const CARE_RELATIONS = [
  { code: "mother", label: "Mother" },
  { code: "father", label: "Father" },
  { code: "parent_in_law", label: "Parent-in-law" },
  { code: "grandparent", label: "Grandparent" },
  { code: "spouse", label: "Spouse" },
  { code: "child", label: "Child" },
  { code: "sibling", label: "Sibling" },
  { code: "other", label: "Other" },
];
export const careRelationLabel = (c?: string) => CARE_RELATIONS.find((r) => r.code === c)?.label ?? (c ?? "");
