import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useStartDiagnostic, useSubmitDiagnosticResult } from "@/hooks/useDiagnostic";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

const ASSESSMENT = {
  assessment_id: "assessment-1", completed_at: null, maximum_items: 1, skill_ids: ["skill-1"],
  started_at: "2026-01-01T00:00:00Z", status: "IN_PROGRESS",
};

describe("diagnostic hooks (integration)", () => {
  it("starts a diagnostic with backend-selected items - the client never picks questions itself", async () => {
    server.use(
      http.post("*/api/v1/adaptive/diagnostics", () =>
        HttpResponse.json(
          {
            assessment: ASSESSMENT,
            items: [
              { assessment_id: "assessment-1", attempt_id: null, completed_at: null, exercise_id: "ex-1",
                item_id: "item-1", normalized_score: null, position: 0, selected_at: "2026-01-01T00:00:00Z",
                skill_ids: ["skill-1"] },
            ],
            recommended_starting_skill_ids: [],
            skill_results: {},
            skill_scores: {},
          },
          { status: 201 }
        )
      )
    );

    const { result } = renderHookWithQuery(() => useStartDiagnostic());
    result.current.mutate({ maximum_items: 1 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0]?.item_id).toBe("item-1");
  });

  it("submitting a diagnostic result returns backend-computed skill readiness, not a client-side score", async () => {
    server.use(
      http.post("*/api/v1/adaptive/diagnostics/assessment-1/items/item-1/result", () =>
        HttpResponse.json({
          assessment: { ...ASSESSMENT, status: "COMPLETED", completed_at: "2026-01-01T00:05:00Z" },
          items: [
            { assessment_id: "assessment-1", attempt_id: "attempt-1", completed_at: "2026-01-01T00:05:00Z",
              exercise_id: "ex-1", item_id: "item-1", normalized_score: 1, position: 0,
              selected_at: "2026-01-01T00:00:00Z", skill_ids: ["skill-1"] },
          ],
          recommended_starting_skill_ids: [],
          skill_results: { "skill-1": "STRONG" },
          skill_scores: { "skill-1": 1 },
        })
      )
    );

    const { result } = renderHookWithQuery(() => useSubmitDiagnosticResult());
    result.current.mutate({ assessmentId: "assessment-1", itemId: "item-1", body: { selected_option_ids: ["a"] } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.skill_results["skill-1"]).toBe("STRONG");
  });
});
