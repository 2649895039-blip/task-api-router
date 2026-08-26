# Promotion Plan

This project is a developer tool. Promotion should show a reproducible result, not only describe the architecture.

## Positioning

Use one sentence everywhere:

> A local task-level LLM router for Claude Code and OpenClaw that routes each task to the cheapest configured model capable of handling it, with a local action guard.

Do not lead with "AI platform" or "best model". Lead with the concrete pain: paying a strong model for every task and manually switching models.

## Assets to prepare

1. A 30-60 second terminal recording showing `--models`, one routed task, and a blocked destructive command.
2. One architecture image: task -> local preclassify -> ranking -> configured provider -> fallback.
3. One copy-paste installation block from the README.
4. A short comparison table: request-level proxy vs task-level router.

## First 14 days

### Days 1-2: credibility

- Pin the repository on your GitHub profile.
- Create a GitHub Release for the latest tag.
- Add one issue labelled `good first issue`, such as adding a provider example.
- Ask two people who actually use Claude Code or OpenClaw to install it and report friction.

### Days 3-6: focused posts

- Publish one technical post on V2EX or 掘金 using the problem/solution format.
- Publish one English post on Reddit (`r/LocalLLaMA`, `r/ClaudeAI`) or Hacker News, only after the README demo works.
- Reply to existing discussions about model cost, routing, and Claude Code hooks. Link only when it directly answers the question.

### Days 7-14: proof and iteration

- Publish the terminal recording and link to the exact README section.
- Turn installer feedback into README fixes and a small patch release.
- Review GitHub traffic, clones, and referral sources. Keep the channel that produces installs, not just views.

## Post template

**Title:** I built a task-level LLM router for Claude Code and OpenClaw

**Body:**

I was paying for the strongest model even for translation and bulk tasks, and manually switching models became annoying. `task-api-router` routes each task by capability and a local ranking table, only among models configured by the user.

It also includes a local PreToolUse action guard for destructive shell commands and out-of-workspace writes. The core is MIT-licensed Python; API keys stay in the user's environment.

Quick start and an offline check:

`https://github.com/2649895039-blip/task-api-router`

I am looking for installation feedback from Claude Code and OpenClaw users, especially where the setup is unclear.

## What to measure

- GitHub unique visitors
- Clone count
- README-to-clone conversion
- Successful installs
- First routed task
- Stars only as a secondary signal

Avoid mass-posting, unsolicited direct messages, fake stars, and claims that the router always saves money. The value is measurable routing and fallback using each user's own configured providers.
