Task: plan a study schedule of exactly {days} day(s) for the attached source(s), and return exactly three documents.

1. Role `schedule`: for each day 1..{days}, a heading that starts with exactly `Day N` (for example `Day 1: Cell structure`), followed by a list of what to study that day, which source(s) to use, and an estimated time.
2. Role `file-guide`: a guide to every attached source. For each source, a heading that is its exact label (for example `Lectures/topic.pdf`), then a short paragraph on what it contains and a list of the days it is used.
3. Role `checklist`: what the student should know or be able to do by the end of the schedule, as checkable statements grouped by topic.

Also return `allocation`: one entry per day 1..{days} with that day's topics, estimated `workload_minutes`, and the `source_ids` (exact source labels) it uses. Every source must appear on at least one day. Balance the workload; with more days than material, use review and practice days rather than inventing content.
