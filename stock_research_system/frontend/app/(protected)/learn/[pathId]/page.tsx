"use client";

import { use } from "react";

import { LearningPathPageContent } from "./LearningPathPageContent";

export default function LearningPathPage({ params }: { params: Promise<{ pathId: string }> }) {
  const { pathId } = use(params);
  return <LearningPathPageContent pathId={pathId} />;
}
