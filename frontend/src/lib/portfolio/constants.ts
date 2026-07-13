/**
 * Portfolio-wide constants. Single source of truth for the setup wizard AND
 * the /portfolio (You -> Portfolio) editor. Nothing outside these lists is
 * exposed to the user — mapping to the backend enums (portfolio_manager.py)
 * happens here so display labels never diverge from stored codes.
 */

// ---------- Days of the week ----------
export const DAYS_OF_WEEK = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;
export type DayOfWeek = typeof DAYS_OF_WEEK[number];

export const DAY_LABELS: Record<DayOfWeek, string> = {
  monday: "Monday",
  tuesday: "Tuesday",
  wednesday: "Wednesday",
  thursday: "Thursday",
  friday: "Friday",
  saturday: "Saturday",
  sunday: "Sunday",
};

// ---------- Time commitment categories (user-facing labels -> backend enum) ----------
export const TIME_CATEGORIES: { code: string; label: string }[] = [
  { code: "sleep", label: "Sleep" },
  { code: "work", label: "Work" },
  { code: "commute", label: "Commute" },
  { code: "study", label: "Study" },
  { code: "meal", label: "Meals" },
  { code: "caregiving", label: "Family / Caregiving" },
  { code: "household", label: "Chores / Household" },
  { code: "health", label: "Exercise / Health" },
  { code: "personal", label: "Personal" },
  { code: "other", label: "Other" },
];

export const TIME_CATEGORY_LABEL: Record<string, string> = TIME_CATEGORIES.reduce(
  (a, c) => ({ ...a, [c.code]: c.label }),
  {} as Record<string, string>,
);

export const FLEXIBILITY_OPTIONS: { code: "fixed" | "flexible"; label: string }[] = [
  { code: "fixed", label: "Fixed" },
  { code: "flexible", label: "Flexible" },
];

// ---------- Financial accounts ----------
// Each account_type is preconfigured with liquidity_type and fixed_or_flexible
// so the setup wizard never asks the user for those two dimensions.
export type AccountKind = "asset" | "liability";
export type AccountPreset = {
  code: string;
  label: string;
  kind: AccountKind;
  liquidity_type: "liquid" | "semi_liquid" | "illiquid";
  fixed_or_flexible: "fixed" | "flexible";
};

export const ACCOUNT_PRESETS: AccountPreset[] = [
  // Assets
  { code: "cash", label: "Cash", kind: "asset", liquidity_type: "liquid", fixed_or_flexible: "flexible" },
  { code: "bank", label: "Bank Account", kind: "asset", liquidity_type: "liquid", fixed_or_flexible: "flexible" },
  { code: "fixed_deposit", label: "Fixed Deposit", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "fixed" },
  { code: "recurring_deposit", label: "Recurring Deposit", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "fixed" },
  { code: "mutual_fund", label: "Mutual Fund", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "flexible" },
  { code: "stock", label: "Stock", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "flexible" },
  { code: "bond", label: "Bond", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "flexible" },
  { code: "crypto", label: "Crypto", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "flexible" },
  { code: "gold", label: "Gold", kind: "asset", liquidity_type: "semi_liquid", fixed_or_flexible: "flexible" },
  { code: "real_estate", label: "Real Estate", kind: "asset", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
  { code: "other_asset", label: "Other Asset", kind: "asset", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
  // Liabilities
  { code: "credit_card", label: "Credit Card Outstanding", kind: "liability", liquidity_type: "liquid", fixed_or_flexible: "flexible" },
  { code: "personal_loan", label: "Personal Loan", kind: "liability", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
  { code: "home_loan", label: "Home Loan", kind: "liability", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
  { code: "vehicle_loan", label: "Vehicle Loan", kind: "liability", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
  { code: "other_liability", label: "Other Liability", kind: "liability", liquidity_type: "illiquid", fixed_or_flexible: "fixed" },
];

export const ACCOUNT_PRESET_BY_CODE: Record<string, AccountPreset> = ACCOUNT_PRESETS.reduce(
  (a, p) => ({ ...a, [p.code]: p }),
  {} as Record<string, AccountPreset>,
);

// ---------- Monthly money commitments ----------
// commitment_type + fixed_or_flexible are auto-set per the spec so the user
// picks a "kind" and everything else falls out from this table.
export type MoneyCommitmentKind = "income" | "expense" | "debt_payment" | "saving" | "investment";
export type MoneyCommitmentPreset = {
  group: "Income" | "Fixed Expenses" | "Debt Payments" | "Savings and Investments";
  label: string;
  commitment_type: MoneyCommitmentKind;
  fixed_or_flexible: "fixed";  // Per spec, everything in Portfolio Setup is fixed.
};

export const MONEY_COMMITMENT_PRESETS: MoneyCommitmentPreset[] = [
  // Income
  { group: "Income", label: "Salary", commitment_type: "income", fixed_or_flexible: "fixed" },
  { group: "Income", label: "Business Income", commitment_type: "income", fixed_or_flexible: "fixed" },
  { group: "Income", label: "Rental Income", commitment_type: "income", fixed_or_flexible: "fixed" },
  { group: "Income", label: "Other Income", commitment_type: "income", fixed_or_flexible: "fixed" },
  // Fixed Expenses
  { group: "Fixed Expenses", label: "Rent", commitment_type: "expense", fixed_or_flexible: "fixed" },
  { group: "Fixed Expenses", label: "Utilities", commitment_type: "expense", fixed_or_flexible: "fixed" },
  { group: "Fixed Expenses", label: "Groceries", commitment_type: "expense", fixed_or_flexible: "fixed" },
  { group: "Fixed Expenses", label: "Insurance", commitment_type: "expense", fixed_or_flexible: "fixed" },
  { group: "Fixed Expenses", label: "Education", commitment_type: "expense", fixed_or_flexible: "fixed" },
  { group: "Fixed Expenses", label: "Other Fixed Expense", commitment_type: "expense", fixed_or_flexible: "fixed" },
  // Debt Payments
  { group: "Debt Payments", label: "Credit Card Payment", commitment_type: "debt_payment", fixed_or_flexible: "fixed" },
  { group: "Debt Payments", label: "Personal Loan EMI", commitment_type: "debt_payment", fixed_or_flexible: "fixed" },
  { group: "Debt Payments", label: "Home Loan EMI", commitment_type: "debt_payment", fixed_or_flexible: "fixed" },
  { group: "Debt Payments", label: "Vehicle Loan EMI", commitment_type: "debt_payment", fixed_or_flexible: "fixed" },
  { group: "Debt Payments", label: "Other Debt Payment", commitment_type: "debt_payment", fixed_or_flexible: "fixed" },
  // Savings and Investments
  { group: "Savings and Investments", label: "Savings", commitment_type: "saving", fixed_or_flexible: "fixed" },
  { group: "Savings and Investments", label: "SIP / Mutual Fund", commitment_type: "investment", fixed_or_flexible: "fixed" },
  { group: "Savings and Investments", label: "Recurring Deposit", commitment_type: "investment", fixed_or_flexible: "fixed" },
  { group: "Savings and Investments", label: "Other Investment", commitment_type: "investment", fixed_or_flexible: "fixed" },
];

// ---------- Time helpers ----------
export const hhmmToMinutes = (s: string): number => {
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(s || "");
  if (!m) return -1;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
};

/** Return an error message if the [start, end) block is invalid, else null. */
export const validateBlockTimes = (start: string, end: string): string | null => {
  const s = hhmmToMinutes(start);
  const e = hhmmToMinutes(end);
  if (s < 0) return "Start time must be HH:MM";
  if (e < 0) return "End time must be HH:MM";
  if (e <= s) return "End time must be after start time";
  if (e > 24 * 60) return "End time cannot cross midnight";
  if (e - s === 0) return "Zero-duration block";
  return null;
};

/**
 * Frontend-only overlap check on the same weekday. The backend does not
 * enforce this in Iteration 1; we run it locally to keep the setup UX honest.
 */
export const hasOverlapOnDay = (
  existing: { id?: string; start_time: string; end_time: string }[],
  candidate: { id?: string; start_time: string; end_time: string },
): boolean => {
  const cs = hhmmToMinutes(candidate.start_time);
  const ce = hhmmToMinutes(candidate.end_time);
  return existing.some((b) => {
    if (candidate.id && b.id === candidate.id) return false;
    const bs = hhmmToMinutes(b.start_time);
    const be = hhmmToMinutes(b.end_time);
    return cs < be && bs < ce;
  });
};

export const localTodayISO = (): string => {
  const d = new Date();
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

export const localMondayISO = (): string => {
  // Anchor at the Monday of the user's current local week — the weekly
  // capacity endpoint rejects anything else.
  const d = new Date();
  const day = d.getDay(); // Sun=0, Mon=1 ... Sat=6
  const diffToMon = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diffToMon);
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

export const localMonthISO = (): string => {
  const d = new Date();
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};

// ---------- Currency list (ISO 4217 active alphabetic codes) ----------
// Sourced from the ISO 4217 published list. Kept as a static array so the
// picker works offline and never depends on a network endpoint.
export const ISO_4217_CURRENCIES: { code: string; name: string }[] = [
  { code: "AED", name: "UAE Dirham" },
  { code: "AFN", name: "Afghani" },
  { code: "ALL", name: "Lek" },
  { code: "AMD", name: "Armenian Dram" },
  { code: "ANG", name: "Netherlands Antillean Guilder" },
  { code: "AOA", name: "Kwanza" },
  { code: "ARS", name: "Argentine Peso" },
  { code: "AUD", name: "Australian Dollar" },
  { code: "AWG", name: "Aruban Florin" },
  { code: "AZN", name: "Azerbaijan Manat" },
  { code: "BAM", name: "Convertible Mark" },
  { code: "BBD", name: "Barbados Dollar" },
  { code: "BDT", name: "Taka" },
  { code: "BGN", name: "Bulgarian Lev" },
  { code: "BHD", name: "Bahraini Dinar" },
  { code: "BIF", name: "Burundi Franc" },
  { code: "BMD", name: "Bermudian Dollar" },
  { code: "BND", name: "Brunei Dollar" },
  { code: "BOB", name: "Boliviano" },
  { code: "BRL", name: "Brazilian Real" },
  { code: "BSD", name: "Bahamian Dollar" },
  { code: "BTN", name: "Ngultrum" },
  { code: "BWP", name: "Pula" },
  { code: "BYN", name: "Belarusian Ruble" },
  { code: "BZD", name: "Belize Dollar" },
  { code: "CAD", name: "Canadian Dollar" },
  { code: "CDF", name: "Congolese Franc" },
  { code: "CHF", name: "Swiss Franc" },
  { code: "CLP", name: "Chilean Peso" },
  { code: "CNY", name: "Yuan Renminbi" },
  { code: "COP", name: "Colombian Peso" },
  { code: "CRC", name: "Costa Rican Colon" },
  { code: "CUP", name: "Cuban Peso" },
  { code: "CVE", name: "Cabo Verde Escudo" },
  { code: "CZK", name: "Czech Koruna" },
  { code: "DJF", name: "Djibouti Franc" },
  { code: "DKK", name: "Danish Krone" },
  { code: "DOP", name: "Dominican Peso" },
  { code: "DZD", name: "Algerian Dinar" },
  { code: "EGP", name: "Egyptian Pound" },
  { code: "ERN", name: "Nakfa" },
  { code: "ETB", name: "Ethiopian Birr" },
  { code: "EUR", name: "Euro" },
  { code: "FJD", name: "Fiji Dollar" },
  { code: "FKP", name: "Falkland Islands Pound" },
  { code: "GBP", name: "Pound Sterling" },
  { code: "GEL", name: "Lari" },
  { code: "GHS", name: "Ghana Cedi" },
  { code: "GIP", name: "Gibraltar Pound" },
  { code: "GMD", name: "Dalasi" },
  { code: "GNF", name: "Guinean Franc" },
  { code: "GTQ", name: "Quetzal" },
  { code: "GYD", name: "Guyana Dollar" },
  { code: "HKD", name: "Hong Kong Dollar" },
  { code: "HNL", name: "Lempira" },
  { code: "HTG", name: "Gourde" },
  { code: "HUF", name: "Forint" },
  { code: "IDR", name: "Rupiah" },
  { code: "ILS", name: "New Israeli Sheqel" },
  { code: "INR", name: "Indian Rupee" },
  { code: "IQD", name: "Iraqi Dinar" },
  { code: "IRR", name: "Iranian Rial" },
  { code: "ISK", name: "Iceland Krona" },
  { code: "JMD", name: "Jamaican Dollar" },
  { code: "JOD", name: "Jordanian Dinar" },
  { code: "JPY", name: "Yen" },
  { code: "KES", name: "Kenyan Shilling" },
  { code: "KGS", name: "Som" },
  { code: "KHR", name: "Riel" },
  { code: "KMF", name: "Comorian Franc" },
  { code: "KPW", name: "North Korean Won" },
  { code: "KRW", name: "Won" },
  { code: "KWD", name: "Kuwaiti Dinar" },
  { code: "KYD", name: "Cayman Islands Dollar" },
  { code: "KZT", name: "Tenge" },
  { code: "LAK", name: "Lao Kip" },
  { code: "LBP", name: "Lebanese Pound" },
  { code: "LKR", name: "Sri Lanka Rupee" },
  { code: "LRD", name: "Liberian Dollar" },
  { code: "LSL", name: "Loti" },
  { code: "LYD", name: "Libyan Dinar" },
  { code: "MAD", name: "Moroccan Dirham" },
  { code: "MDL", name: "Moldovan Leu" },
  { code: "MGA", name: "Malagasy Ariary" },
  { code: "MKD", name: "Denar" },
  { code: "MMK", name: "Kyat" },
  { code: "MNT", name: "Tugrik" },
  { code: "MOP", name: "Pataca" },
  { code: "MRU", name: "Ouguiya" },
  { code: "MUR", name: "Mauritius Rupee" },
  { code: "MVR", name: "Rufiyaa" },
  { code: "MWK", name: "Malawi Kwacha" },
  { code: "MXN", name: "Mexican Peso" },
  { code: "MYR", name: "Malaysian Ringgit" },
  { code: "MZN", name: "Mozambique Metical" },
  { code: "NAD", name: "Namibia Dollar" },
  { code: "NGN", name: "Naira" },
  { code: "NIO", name: "Cordoba Oro" },
  { code: "NOK", name: "Norwegian Krone" },
  { code: "NPR", name: "Nepalese Rupee" },
  { code: "NZD", name: "New Zealand Dollar" },
  { code: "OMR", name: "Rial Omani" },
  { code: "PAB", name: "Balboa" },
  { code: "PEN", name: "Sol" },
  { code: "PGK", name: "Kina" },
  { code: "PHP", name: "Philippine Peso" },
  { code: "PKR", name: "Pakistan Rupee" },
  { code: "PLN", name: "Zloty" },
  { code: "PYG", name: "Guarani" },
  { code: "QAR", name: "Qatari Rial" },
  { code: "RON", name: "Romanian Leu" },
  { code: "RSD", name: "Serbian Dinar" },
  { code: "RUB", name: "Russian Ruble" },
  { code: "RWF", name: "Rwanda Franc" },
  { code: "SAR", name: "Saudi Riyal" },
  { code: "SBD", name: "Solomon Islands Dollar" },
  { code: "SCR", name: "Seychelles Rupee" },
  { code: "SDG", name: "Sudanese Pound" },
  { code: "SEK", name: "Swedish Krona" },
  { code: "SGD", name: "Singapore Dollar" },
  { code: "SHP", name: "Saint Helena Pound" },
  { code: "SLE", name: "Leone" },
  { code: "SOS", name: "Somali Shilling" },
  { code: "SRD", name: "Surinam Dollar" },
  { code: "SSP", name: "South Sudanese Pound" },
  { code: "STN", name: "Dobra" },
  { code: "SVC", name: "El Salvador Colon" },
  { code: "SYP", name: "Syrian Pound" },
  { code: "SZL", name: "Lilangeni" },
  { code: "THB", name: "Baht" },
  { code: "TJS", name: "Somoni" },
  { code: "TMT", name: "Turkmenistan New Manat" },
  { code: "TND", name: "Tunisian Dinar" },
  { code: "TOP", name: "Pa'anga" },
  { code: "TRY", name: "Turkish Lira" },
  { code: "TTD", name: "Trinidad and Tobago Dollar" },
  { code: "TWD", name: "New Taiwan Dollar" },
  { code: "TZS", name: "Tanzanian Shilling" },
  { code: "UAH", name: "Hryvnia" },
  { code: "UGX", name: "Uganda Shilling" },
  { code: "USD", name: "US Dollar" },
  { code: "UYU", name: "Peso Uruguayo" },
  { code: "UZS", name: "Uzbekistan Sum" },
  { code: "VES", name: "Bolivar Soberano" },
  { code: "VND", name: "Dong" },
  { code: "VUV", name: "Vatu" },
  { code: "WST", name: "Tala" },
  { code: "XAF", name: "CFA Franc BEAC" },
  { code: "XCD", name: "East Caribbean Dollar" },
  { code: "XOF", name: "CFA Franc BCEAO" },
  { code: "XPF", name: "CFP Franc" },
  { code: "YER", name: "Yemeni Rial" },
  { code: "ZAR", name: "Rand" },
  { code: "ZMW", name: "Zambian Kwacha" },
  { code: "ZWG", name: "Zimbabwe Gold" },
];

export const CURRENCY_LABEL = (code: string): string => {
  const c = ISO_4217_CURRENCIES.find((x) => x.code === code);
  return c ? `${c.code} — ${c.name}` : code;
};

/** Format a stored decimal string for display (thousands separators). */
export const formatMoney = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined) return "0";
  const s = typeof value === "number" ? String(value) : value;
  const [intPart, fracPart] = s.split(".");
  const withThousands = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fracPart ? `${withThousands}.${fracPart}` : withThousands;
};
