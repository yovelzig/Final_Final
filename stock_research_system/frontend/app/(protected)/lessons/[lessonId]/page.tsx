"use client";

import { use } from "react";

import { LessonPageContent } from "./LessonPageContent";

export default function LessonPage({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = use(params);
  return <LessonPageContent lessonId={lessonId} />;
}
