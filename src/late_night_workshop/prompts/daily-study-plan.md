Task: split the attached source(s) into a daily study plan of exactly {days} day(s). Each day gets its own three documents.

- First decide the allocation: distinct topics per day, ordered so earlier days build foundations, with balanced workload. Do not repeat the same material every day; with more days than material, later days may be review and practice of earlier topics, but each day's documents must still differ.
- Return `allocation`: one entry per day 1..{days} with its `topics`, estimated `workload_minutes`, and the `source_ids` (exact source labels) it draws on. Every source must appear on at least one day.
- For EACH day N, return three documents with `day` = N:
  - role `notes`: study notes covering only that day's topics.
  - role `sample-questions`: practice questions on exactly the material in that day's notes, as `question` blocks labelled `Q1`, `Q2`, ..., then a heading `Answers` followed by one `question` block per answer whose `label` repeats the question's label (`Q1`, `Q2`, ...) and whose `text` is a short model answer.
  - role `checklist`: what the student should know by the end of that day, matching that day's notes.
- Start each document's title with `Day N:` followed by the day's topic.
