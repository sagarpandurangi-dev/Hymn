/**
 * Family net worth helpers. The server has no "list entries" call, so entries
 * added from this phone are remembered here (per family) to allow deleting them.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

export const FAMILY_RELATIONS = [
  { code: "spouse", label: "Spouse" },
  { code: "child", label: "Child" },
  { code: "parent", label: "Parent" },
  { code: "sibling", label: "Sibling" },
  { code: "other", label: "Other" },
];

export const ASSET_GROUPS = [
  { code: "fixed", label: "Fixed (home, land, vehicles)" },
  { code: "investments", label: "Investments" },
  { code: "retirement", label: "Retirement" },
  { code: "deposits", label: "Deposits" },
  { code: "cash", label: "Cash" },
];
export const LIABILITY_GROUPS = [
  { code: "loans", label: "Loans" },
  { code: "current", label: "Current (cards, dues)" },
];

export const groupLabel = (code: string) =>
  [...ASSET_GROUPS, ...LIABILITY_GROUPS].find((g) => g.code === code)?.label.replace(/ \(.*\)$/, "") ?? code;

export const relationLabel = (r?: string) =>
  r === "self" ? "Started the family" : FAMILY_RELATIONS.find((x) => x.code === r)?.label ?? (r || "");

export type SavedFamilyItem = { id: string; side: string; group: string; name: string; amount: string; shares: Record<string, string | number> };

const key = (familyId: string) => `hymn.family.items.${familyId}`;

export async function loadFamilyItems(familyId: string): Promise<SavedFamilyItem[]> {
  try {
    const raw = await AsyncStorage.getItem(key(familyId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export async function saveFamilyItems(familyId: string, items: SavedFamilyItem[]): Promise<void> {
  await AsyncStorage.setItem(key(familyId), JSON.stringify(items));
}

/**
 * The member row that is me. Members carry no user id, so: the id remembered
 * when I accepted an invite, else the "self" row if I created the family,
 * else a joined app user with my name.
 */
export const findMe = (members: any[], family: any, user: any, savedId?: string | null) =>
  members.find((m) => savedId && m.id === savedId) ??
  (family?.owner_user_id && family.owner_user_id === user?.id ? members.find((m) => m.relation === "self") : undefined) ??
  members.find((m) => m.kind === "user" && m.relation !== "self" && m.status === "active" && !!user?.name && (m.name === user.name || m.name === String(user.name).split(" ")[0]));

const meKey = (familyId: string) => `hymn.family.me.${familyId}`;
export const saveMyMemberId = (familyId: string, memberId: string) => AsyncStorage.setItem(meKey(familyId), memberId).catch(() => undefined);
export const loadMyMemberId = (familyId: string) => AsyncStorage.getItem(meKey(familyId)).catch(() => null);
