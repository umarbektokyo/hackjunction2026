# Earned Trust in AI Code

**By:** Tieto · **Type:** Main challenge · **Track:** Agentic AI Track · **Tags:** AI

**Page:** https://hackjunction.app/participate/45/challenges/351 · **Website:** https://www.tieto.com/

How does AI code review keep pace with AI-written code, while humans stay accountable for every change?

## Introduction
It is Friday afternoon. A pull request lands from an agent. Two hundred lines, and your name is on the approval. Usually you would open the diff and start digging. But what if the change opened with its own explanation? What it does, why it was made, what else it touches, and how sure the AI is about each part. Suddenly you are not hunting for problems. You are checking a story, and questioning the parts that do not add up.

Pick **Earned Trust in AI Code**, and help define how code explains itself now and in the future.

## Background
- Agent tokens passed human tokens in February 2026 and reached 7.3 trillion by August (OpenRouter data, a16z chart).
- Reviewing every change by hand does not scale, yet engineers need a sound basis to trust AI-reviewed code.

## The challenge
Design an **AI code review concept**, then show it works. Define the concept, principles, reference implementation and technology considerations, across frontend, backend and security.

Challenge the traditional model: **is line-by-line review still the right way to ensure quality?** Balance risk, hallucination, transparency, confidence and quality in AI review. The result is a reference implementation that illustrates the concept – it is not a product.

### What we expect from each team
1. **Define the concept:** what your team recommends the "PR review" factory should follow.
2. **State its key principles**, including how it balances risk, hallucination, transparency, confidence and quality.
3. **Illustrate it as a reference**, on one sample agent-written change with its requirement ID.
4. **Show what the AI found**, what it refused to decide, and why.
5. **Show how the evidence** lets a named human accept the change without a full read.
6. **Name the failure modes** you saw, and keep a short log of decisions.

*Use synthetic or cleared sample data only.*

###Code input for the challenge

As an input for the challenge, please feel inspired but not limited with the code examples that we have collected for you.
The repo is here (please make your own copy of this repo before you start the work)
https://github.com/te-industry-tech-office/junction26-messagepack-csharp
In the repo, you can find the following branches that contain code changes made by AI.

branch ju26-issue-2283 with agentic implementation of bug #2283 (https://github.com/MessagePack-CSharp/MessagePack-CSharp/issues/2283); this contains a commit of 4 files

branch ju26-issue-2234 with agentic implementation of bug #2234 (https://github.com/MessagePack-CSharp/MessagePack-CSharp/issues/2234); this contains a commit of 4 files

branch ju26-issue-2129 with agentic implementation of issue #2129 (https://github.com/MessagePack-CSharp/MessagePack-CSharp/issues/2129); this contains a commit of 28 files

branch ju26-issue-2297 with agentic implementation of issue #2297 (https://github.com/MessagePack-CSharp/MessagePack-CSharp/issues/2297); this contains a commit of 237 files

We encourage to think "outside of the box" and in our evaluation we put more weight for the concept than only the technical implementation.
"HOW CAN AI REVIEW THE CODE MADE BY AI SO THAT HUMANS CAN TRUST IT?"

### Deliverables
- **Concept card:** recommendation, principles, trade-offs, limits
- **Live walkthrough** showing where the trust comes from
- **Lessons log** and a demo video/presentation

**Out of scope:** a finished product, model training and vendor selection.

**Expected outcome:** a concept with explicit trade-offs that humans can trust and be accountable for.

## Resources

## What we'll bring
- **Background on what good code means at Tieto:** standards, security and quality
- **A requirements set:** intent, functional and non-functional
- **Sample agent-written changes**, each with its requirement ID

## Model access
You have access to models from other Junction partners through **partner credits on the Junction Platform**. Connect any of these models to your concept.

## Judging criteria

- **Clarity** (30%) – A clear recommendation with stated principles, explicit trade-offs and limits.
- **Practicality** (25%) – The concept could work in a real pull-request flow and scale, with a named human owning each decision.
- **Measurement** (25%) – Shows how trust is measured: reverts and incidents don't rise as review time falls, AI findings are real and accepted, time to merge, share routed to humans.
- **Evidence** (20%) – Evidence traceable to a requirement lets a named human accept a change without a full read, incl. what the AI found, what it refused to decide, and why.

## Prizes

- **1st Place:** €2,000 cash prize for the winning team.
- **2nd Place:** €1,000 cash prize for the runner-up team.
- **3rd Place:** €500 cash prize for the third-place team.
