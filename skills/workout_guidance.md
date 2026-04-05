---
id: workout_guidance
title: Workout Guidance
executor: workout_guidance
kind: context
enabled_by_default: true
description: Search exercise database for workout routines, exercises by muscle group, equipment, and difficulty level.
---

# Workout Guidance Skill

Use this skill to provide personalized exercise recommendations from a local
database of 800+ exercises.

Essential guidance:
- Run for context handling.
- First call `functions.workout_search.needs_workout_data(query)`.
- If workout data is not needed, return `activated=false`.
- If workout data is needed, call `functions.workout_search.search_exercises(query)`
  and `functions.workout_search.format_exercise_results(...)`.
- Required input: `query`.
- Return `activated=true` with `workout_summary`.

## Planning Behavior — User Experience First

Workout plans must feel like a conversation, not a prescription. Users lose patience when hit with a wall of exercises. Keep it short, dynamic, and collaborative.

- **One week maximum.** Never generate workout plans longer than 7 days. For longer programs, plan one week at a time and revisit based on how it went.
- **Lead with a quick overview, not the full plan.** When the user asks for a plan, first propose the high-level structure — e.g. "3 days: Mon (upper), Wed (lower), Fri (full body)" — and wait for their OK before generating exercise details.
- **Show one day at a time by default.** After the overview is agreed on, present today's workout (or the next training day). Only show the full week if the user explicitly asks.
- **No repeating weeks.** Don't auto-repeat a template. Each new week is a chance to adjust based on progress, soreness, schedule changes, etc.
- **Keep exercise lists tight.** 4-6 exercises per session is plenty for most users. Don't overload with 8+ exercises unless the user is advanced and asks for volume.
- **Always invite feedback.** After presenting a day's workout, ask: "Does this look good, or want me to swap anything?" Make it feel like a collaboration.

Routing keywords: exercise workout fitness gym training muscle chest back legs
arms shoulders abs core biceps triceps quadriceps hamstrings glutes calves
dumbbell barbell kettlebell bodyweight resistance band cable machine beginner
intermediate advanced strength cardio stretching flexibility warmup cooldown
routine repetitions sets reps squat deadlift bench press pull-up push-up
