import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { LearningPathPageContent } from "@/app/(protected)/learn/[pathId]/LearningPathPageContent";
import { ModuleSection } from "@/components/learning/ModuleSection";
import { server } from "@/tests/mocks/server";
import { renderWithQuery, screen } from "@/tests/test-utils";
import type { LearningModuleResponse } from "@/types/api-schemas";

const PATH_ID = "path-1";

const MODULE: LearningModuleResponse = {
  module_id: "module-1",
  path_id: PATH_ID,
  code: "m1",
  title: "Money and Inflation",
  description: "Learn the basics.",
  position: 0,
  estimated_minutes: 20,
  published: true,
};

describe("curriculum empty states", () => {
  it("shows an empty state when a learning path has zero visible modules", async () => {
    server.use(
      http.get(`*/api/v1/learning-paths/${PATH_ID}`, () =>
        HttpResponse.json({
          path_id: PATH_ID,
          code: "p1",
          title: "Investing Foundations",
          description: "Start here.",
          difficulty: "BEGINNER",
          position: 0,
          estimated_minutes: 60,
          published: true,
        })
      ),
      http.get(`*/api/v1/learning-paths/${PATH_ID}/modules`, () => HttpResponse.json([]))
    );

    renderWithQuery(<LearningPathPageContent pathId={PATH_ID} />);

    expect(await screen.findByText("No modules are available in this learning path yet.")).toBeInTheDocument();
  });

  it("shows an empty state when a module has zero visible lessons", async () => {
    server.use(
      http.get(`*/api/v1/modules/${MODULE.module_id}/lessons`, () => HttpResponse.json([])),
      http.get("*/api/v1/learners/me/progress", () =>
        HttpResponse.json({ items: [], pagination: { limit: 50, offset: 0, returned: 0, total: 0 } })
      )
    );

    renderWithQuery(<ModuleSection module={MODULE} />);

    expect(await screen.findByText("No lessons are available in this module yet.")).toBeInTheDocument();
  });
});
