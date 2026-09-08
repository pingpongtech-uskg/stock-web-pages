export const CRITERIA_GROUPS = [
  { id: "safety", label: "安全", count: 6 },
  { id: "dividend", label: "股利", count: 5 },
  { id: "growth", label: "成長", count: 5 },
  { id: "value", label: "估值", count: 6 },
  { id: "turnaround", label: "轉機", count: 3 },
  { id: "continuity", label: "續優", count: 5 },
  { id: "chip", label: "籌碼", count: 3 },
] as const;

export type CriteriaGroupId = (typeof CRITERIA_GROUPS)[number]["id"];
export type CriteriaStatus = "ok" | "missing" | "blocked" | "parse_error" | "stale";
export type CriteriaResult = "pass" | "fail" | "unknown" | "blocked";

export interface CriteriaGroupResult {
  status?: CriteriaStatus;
  passed?: number | null;
  count?: number | null;
  pass_ratio?: number | null;
  threshold?: number;
  result?: CriteriaResult;
  missing_reason?: string | null;
}

export type CriteriaGroups = Partial<Record<CriteriaGroupId, CriteriaGroupResult>>;

export function criteriaMeta(groups: CriteriaGroups | null | undefined): { passed: number; complete: boolean } {
  const source = groups ?? {};
  const passed = CRITERIA_GROUPS.filter((group) => source[group.id]?.status === "ok" && source[group.id]?.result === "pass").length;
  const complete = CRITERIA_GROUPS.every((group) => source[group.id]?.status === "ok");
  return { passed, complete };
}

export function groupResult(
  group: (typeof CRITERIA_GROUPS)[number],
  groups: CriteriaGroups | null | undefined,
) {
  const result = groups?.[group.id];
  if (!result || result.status !== "ok" || result.result === "unknown") {
    return {
      state: "unknown" as const,
      symbol: "?",
      detail: result?.missing_reason || "七類 exact criteria 尚未寫入此 snapshot",
    };
  }
  const passed = typeof result.passed === "number" ? result.passed : null;
  const count = typeof result.count === "number" ? result.count : group.count;
  const pass = result.result === "pass";
  return {
    state: pass ? ("pass" as const) : ("fail" as const),
    symbol: pass ? "✓" : "×",
    detail: `${passed ?? "—"}/${count}`,
  };
}
