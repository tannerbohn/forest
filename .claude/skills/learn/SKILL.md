---
name: learn
description: Generate a learning tree for studying a topic, structured as a Q&A tree for the Forest note-taking app
argument-hint: "[topic]"
user-invocable: true
disable-model-invocation: true
---

# Learning Tree Generator

Generate a learning tree for the Forest note-taking app on the following topic:

**$ARGUMENTS**

If no topic was provided (i.e. `$ARGUMENTS` is empty), ask the user what topic they'd like to learn about before proceeding.

## Pre-Generation Level Probing

Before generating the tree, ask the user 2-4 quick questions to gauge their existing familiarity with the topic. These should help you calibrate depth, vocabulary, and emphasis. Examples:

- "Have you encountered X before, or is this completely new?"
- "Do you know what Y means in this context?"
- "Are you looking for a broad overview or a deep dive into specifics?"
- "Is there a particular aspect of X you're most interested in?"

Use the answers to adjust: skip basics the user already knows, go deeper on areas they're curious about, and match the vocabulary level they're comfortable with.

**Skip probing** if the user explicitly states their level (e.g., "I'm a beginner at X") or asks you to just generate without questions.

## Output

Write the tree to a file in `trees/` using a short, lowercase, underscore-separated filename (e.g., `trees/common_lisp.txt`, `trees/graph_theory.txt`). If a file already exists for this topic, ask the user before overwriting.

## Format

The file uses Forest's tab-indented node format. Every line starts with `- ` and children are indented one tab deeper than their parent.

```
- Top-level node
	- Child node
		- Grandchild node
```

## Structure: Question → Answer Tree

The tree is structured as recursive Q&A:

- **Structural nodes must be questions or answers** — no bare section headers like "Getting Started" or "Functions". Top-level nodes are broad questions that motivate exploring a branch (e.g., "How do I get started with X?"). Section-level questions still need a concise first-child answer. Elaboration nodes (2nd child onward) may be plain statements, examples, or annotations — they don't need to be questions.
- **Question nodes** end with `::` (after any trailing `?`) — the `::` suffix marks them as flashcards whose first child is the answer. Hashtags like `#HL1` may follow the `::`.
- **The first child of a question is its answer** — this is the flashcard "back". It must be a **single, self-contained node**. Keep it concise: 1-2 sentences, ideally under 100 characters. If an answer has two parts, combine them into one node (e.g., "' quotes data, #' quotes functions"). If they're truly separate concepts, split into two separate questions instead.
- **Subsequent children** elaborate with examples, caveats, or deeper follow-up questions

Example structure (note how related questions are grouped under abstract parents rather than listed as flat siblings):

```
- What is X? :: #HL1
	- X is the foundation of Y — it represents Z #HL2
	- This means you can do A, B, and C
	- How does X differ from W? ::
		- X is faster but W is more ergonomic
- How do I write X code? ::
	- Everything follows the pattern (op arg1 arg2) — always prefix notation
	- What is the basic syntax? ::
		- (operator arg1 arg2 ...) — prefix, always #HL3
		- (+ 1 2) => 3, (* 3 (+ 1 2)) => 9
	- How does X handle data? ::
		- All data is built from two primitives: atoms and pairs
		- What is an atom in X? ::
			- The simplest indivisible value — numbers, strings, symbols
		- What is a pair (cons cell) in X? ::
			- A structure holding two values — the building block of all lists and trees #HL3
			- (cons 1 2) => (1 . 2)
```

**Anti-pattern** — too wide, not grouped:

```
- How does X handle data? ::
	- ...
	- What is an atom? ::
	- What is a pair? ::
	- What is a list? ::
	- What is a vector? ::
	- What is a hash table? ::
	- What is a struct? ::
```

Better — grouped under abstract parents:

```
- How does X handle data? ::
	- ...
	- What are the primitive data types? ::
		- ...
		- What is an atom? ::
		- What is a pair? ::
	- What are the collection types? ::
		- ...
		- What is a list? ::
		- What is a vector? ::
		- What is a hash table? ::
	- How do you define custom types? ::
		- ...
		- What is a struct? ::
```

## Narrative Flow

Each top-level branch should explicitly motivate the next sibling. The final elaboration nodes of a branch should raise a question, mention a key term, or directly point forward so the reader understands *why* the next section matters. This applies to top-level siblings only — don't try to chain every node at every depth.

Use elaboration nodes (2nd child onward) with explicit forward references. These can be phrased as:
- Open questions: "but what makes an outcome 'stable'?"
- Direct pointers: "the next section explores how..."
- Statements that name the next concept and leave it unresolved

**Without flow** — disconnected sections:
```
- What is a dominant strategy? ::
	- A strategy that is best regardless of what opponents choose
	- e.g. in Prisoner's Dilemma, defecting dominates cooperating
- What is Nash equilibrium? ::
	- ...
```

**With flow** — the previous branch explicitly motivates the next:
```
- What is a dominant strategy? ::
	- A strategy that is best regardless of what opponents choose
	- e.g. in Prisoner's Dilemma, defecting dominates cooperating
	- When every player plays a dominant strategy, the outcome is stable — this stability is formalized as "Nash equilibrium"
- What is Nash equilibrium? ::
	- A state where no player can improve by unilaterally changing strategy — the formal notion of stability
	- ...
```

Notice how the last elaboration node of "dominant strategy" names "Nash equilibrium" and frames it as an open concept, making the transition feel motivated rather than arbitrary.

## Synthesis Questions

Intersperse open-ended synthesis questions throughout the tree to challenge the reader to connect ideas. These appear every 2-3 top-level branches (roughly every 15-25 nodes) and require the reader to synthesize concepts covered since the last synthesis question.

**Rules:**
- Tagged with `#HL3` so they stand out visually
- The answer node should be encoded with ROT13 (`python3 -c "import codecs; print(codecs.encode('Text to encode', 'rot_13'))"`) so that it is available for the user, but cannot be trivially accessed, encouraging the reader to think through independently.
- Placed as a final child of the branch they cap off (not as a separate top-level node)
- Should require connecting, comparing, or applying multiple concepts — not just recalling a single fact

**Example:**

```
- How do I write X code? ::
	- ...
	- How does X handle data? ::
		- ...
	- Think: if X uses prefix notation and all data is built from pairs, what does that imply about how code and data relate? #HL3 ::
		- Guvf vf gur nafjre.
```

Good synthesis prompts: "How does X relate to Y?", "If you changed Z, what would happen to W?", "Why can't you combine A and B?", "What would break if X didn't have property Y?"

## Highlights

Use Forest's highlight hashtags to mark important nodes. Three-tier system:

- **#HL1** — Deep, interesting, conceptually rich questions. Things that provoke insight, touch foundational ideas, reveal surprising connections, or capture the "soul" of a concept. Examples: "Why was Lisp invented?", "What is homoiconicity?", philosophical underpinnings, counterintuitive facts.

- **#HL2** — Notable answers and elaboration under #HL1 questions. The "interesting insight" answer that belongs visually with its #HL1 parent. Use on the first-child answer of an #HL1 question.

- **#HL3** — Critical must-know facts, core syntax, gotchas, common pitfalls. "You must know this" answers. Use on the answer node, not the question.

**Do not double-tag:** Place the highlight on whichever node benefits most from being visually marked — typically the answer (since that's what you're learning). Never tag both a question and its first-child answer with the same highlight.

Use highlights sparingly — roughly 10-20% of nodes. Not everything is critical or deeply interesting.

## Annotation Prefixes

Elaboration nodes (2nd child onward, never on question or answer nodes) can use these prefixes to signal their role:

| Prefix | Role | Use for |
|--------|------|---------|
| `e.g.` | Example | Concrete illustrations, code snippets, scenarios |
| `i.e.` | Clarification | Restating or defining a term inline |
| `nb.` | Caveat/warning | Gotchas, common mistakes, exceptions |
| `cf.` | Cross-reference | Pointer to a related branch using `[[path]]` |

These help readers scan a branch and distinguish supporting material from core content.

Example:

```
- What is fajin? ::
	- Explosive whole-body power release through coordinated structure
	- e.g. the punch at the end of Buddha's Warrior Pounds Mortar
	- nb. requires song (relaxation) as a prerequisite — tension blocks the wave
	- cf. [[How does song enable power? > What is song?]]
```

## Cross-References

Use `[[path > to > node]]` with the `cf.` prefix to point readers to related branches. The path doesn't need to be an exact text match — approximate is fine. Forest renders `[[...]]` content with dim styling.

```
- cf. [[What are the five elements? > What is metal?]]
```

## Flashcard-Friendly Writing

Question nodes ending with `::` become flashcards — the `::` tells Forest that the first child is the answer. Every question node must have this suffix.

- **Questions must be self-contained.** A reader should understand the question without seeing its parent node. Bad: "What about the second type? ::" Good: "What is the second type of polymorphism? ::"
- **Answers (first child) must be concise.** Put the core fact in the first child. Move elaboration, examples, and nuance into subsequent siblings.
- **Prefer "what", "how", "why" questions** that test understanding. Avoid yes/no questions.
- **One concept per question.** Don't combine multiple ideas into a single Q&A.

### Enumeration Pattern

When a question's answer is a list of items:

1. **First child** gives the concise overview (the flashcard answer) — e.g., "The five elements: metal, water, wood, fire, earth"
2. **Sub-questions** drill into each item individually

This way the flashcard tests recall of the full list, and the sub-branches teach each item in depth.

```
- What are the five elements in Chinese philosophy? ::
	- Metal, water, wood, fire, earth — a cycle of generation and control
	- What is the metal element? ::
		- Associated with contraction, structure, and cutting
	- What is the water element? ::
		- Associated with flowing, sinking, and adaptability
```

Do **not** cram 4-8 items into a single answer node — split them into sub-questions.

## Scope and Depth

- **5-10 top-level sections** covering the topic from fundamentals to intermediate concepts
- **Prefer depth over breadth.** When a section has many sibling questions (more than ~4-5), group related ones under a higher-level or more abstract parent question. The tree should grow deep rather than wide — a section with 3 well-organized sub-branches of depth 4-5 is better than 8 flat siblings at depth 2. Think: "What umbrella question would a learner ask that naturally leads to these details?"
- **Depth target: 4-6 levels** of nesting is typical; going to 7 is fine for naturally deep topics
- **Max ~4-5 sibling questions** at any level before you should consider grouping them under a parent
- Begin with foundational "what is it" and "why does it matter" questions, then build toward practical usage and deeper concepts
- Include concrete examples (code snippets, formulas, scenarios) as elaboration nodes where helpful

## Tangents & Surprises

After the main ordered tree, add a final top-level branch called **"Tangents & Surprises"** containing 5-8 child nodes. These are the ideas that make a learner go "wait, really?" and pull them deeper into the topic on their own.

Content types to include:
- Cross-domain connections (how this topic shows up in unexpected fields)
- Historical oddities (surprising origins, failed alternatives, naming accidents)
- Philosophical implications (what this concept means at a deeper level)
- Controversial or counterintuitive takes
- Rabbit holes worth exploring

**Structure is freeform** — nodes can be questions with `::`, plain statements, or mini-branches with children. No rigid format required. Use whatever shape best serves each idea.

Use `cf.` cross-references back to the main tree where relevant. Tag with `#HL1` sparingly — only for the genuinely surprising or profound ones.

```
- Tangents & Surprises
	- The inventor of X originally built it to solve a completely different problem — Y was an accident #HL1
	- How does X connect to fields outside computer science? ::
		- X's core algorithm is identical to how ant colonies optimize foraging routes
		- cf. [[What is the core algorithm of X?]]
	- Controversial: some researchers argue X is fundamentally flawed because...
		- The main counterargument is...
	- If you want to go deeper: look into Y — it generalizes X in a way that breaks most people's intuitions
```
