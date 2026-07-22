"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AttemptResponse,
  ExerciseResponse,
  LearningModuleResponse,
  LearningPathResponse,
  LessonResponse,
  StartAttemptRequest,
  SubmitAnswerRequest,
  SubmitAnswerResponse,
} from "@/types/api-schemas";

export function useLearningPaths() {
  return useQuery({
    queryKey: queryKeys.curriculum.paths(),
    queryFn: () => apiClient.get<LearningPathResponse[]>("/api/v1/learning-paths"),
  });
}

export function useLearningPath(pathId: string) {
  return useQuery({
    queryKey: queryKeys.curriculum.path(pathId),
    queryFn: () => apiClient.get<LearningPathResponse>(`/api/v1/learning-paths/${pathId}`),
    enabled: !!pathId,
  });
}

export function useModules(pathId: string) {
  return useQuery({
    queryKey: queryKeys.curriculum.modules(pathId),
    queryFn: () => apiClient.get<LearningModuleResponse[]>(`/api/v1/learning-paths/${pathId}/modules`),
    enabled: !!pathId,
  });
}

export function useLessons(moduleId: string) {
  return useQuery({
    queryKey: queryKeys.curriculum.lessons(moduleId),
    queryFn: () => apiClient.get<LessonResponse[]>(`/api/v1/modules/${moduleId}/lessons`),
    enabled: !!moduleId,
  });
}

export function useLesson(lessonId: string) {
  return useQuery({
    queryKey: queryKeys.curriculum.lesson(lessonId),
    queryFn: () => apiClient.get<LessonResponse>(`/api/v1/lessons/${lessonId}`),
    enabled: !!lessonId,
  });
}

export function useLessonExercises(lessonId: string) {
  return useQuery({
    queryKey: queryKeys.curriculum.exercises(lessonId),
    queryFn: () => apiClient.get<ExerciseResponse[]>(`/api/v1/lessons/${lessonId}/exercises`),
    enabled: !!lessonId,
  });
}

export function useExercise(exerciseId: string | null) {
  return useQuery({
    queryKey: queryKeys.curriculum.exercise(exerciseId ?? ""),
    queryFn: () => apiClient.get<ExerciseResponse>(`/api/v1/exercises/${exerciseId}`),
    enabled: !!exerciseId,
  });
}

export function useAttempt(attemptId: string | null) {
  return useQuery({
    queryKey: queryKeys.curriculum.attempt(attemptId ?? ""),
    queryFn: () => apiClient.get<AttemptResponse>(`/api/v1/attempts/${attemptId}`),
    enabled: !!attemptId,
  });
}

export function useStartAttempt(exerciseId: string) {
  return useMutation({
    mutationFn: (body: StartAttemptRequest) =>
      apiClient.post<AttemptResponse>(`/api/v1/exercises/${exerciseId}/attempts`, body),
  });
}

export function useSubmitAnswer(attemptId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SubmitAnswerRequest) =>
      apiClient.post<SubmitAnswerResponse>(`/api/v1/attempts/${attemptId}/answers`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.dashboard() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.mastery() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.progress() });
    },
  });
}
