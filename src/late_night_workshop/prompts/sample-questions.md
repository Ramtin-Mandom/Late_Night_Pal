Write one document with role sample-questions: a practice test in the style of a real exam, followed by its full answer key.

Start with a short paragraph, without a heading, saying what the set covers and how to use it (for example: try every question before looking at the answers; give exact answers). Cover the major topics and every attached source with usable material.

Design questions a student can attempt from the material provided, from routine to challenging. Mix retrieval, computation, explanation and proof according to the subject, and include a question that asks the student to choose or justify a method where that is a learning objective. Use self-contained givens. Phrase invented real-world scenarios as hypothetical. For a figure-based question, identify the figure or reproduce its necessary legible values. Wrong options in multiple choice should be the answers a student gets from a typical mistake.

Lay it out in two parts:
1. \practicesection{Practice · Multiple choice} with one short sentence of instructions, then an enumerate of questions, each followed by \choices{...}{...}{...}{...}. Number questions continuously.
2. \practicesection{Practice · Written response} with one sentence of instructions, then one \subsection*{W1 · Topic} per question (W1, W2, ...), with parts (a), (b) where useful, each followed by \workspace.

Then \answersection{Answer key · Multiple choice}: an enumerate with one line per question in the same order, \ans{letter} followed by the decisive reason or calculation. Then \answersection{Answer key · Written response}: one \subsection*{W1 · Topic} per written question, with a complete model solution a grader would accept, steps on display lines and the final results boxed with \boxans. Add a short pitfall callout where students commonly go wrong. Check that each answer follows from the givens in its own question.
