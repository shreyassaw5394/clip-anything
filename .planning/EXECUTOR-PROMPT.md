# Executor prompt template (paste; fill the two blanks)

Execute `.planning/phases/<PHASE>/<PLAN>-PLAN.md` in ~/office-fighter.
Read ONLY `.planning/GRAPH.md` (rules, numbers, seams, file ownership, phase node) and your plan, then the files your plan names. Do not read other plans or summaries unless GRAPH.md points you to one.
Obey every rule in GRAPH.md. Claim your files by adding a line under "File ownership right now" before you start; remove it when done.
When finished: write `<PLAN>-SUMMARY.md` (≤ 25 lines), append one line to GRAPH.md's executor log, update any number you changed, commit docs with your code under the lock. Report ≤ 120 words: commits, check result, deviations, unverified.
