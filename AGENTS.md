# FocusList repository instructions

Read [the condensed SRS](FocusList_SRS_Condensed.docx), [the course brief](Project_1_YouTube_MCP.pdf) and the relevant section of [the commit plan](FocusList_Commit_Plan.md) before making an assignment's changes. The condensed SRS controls scope. Put unresolved decisions in the applicable ADR or SRS TBD and record the evidence.

- Keep official YouTube Data API access behind `VideoProvider`. Keep Google API client imports in the platform package. MCP stdio is for protocol traffic. Keep diagnostics on stderr or in a sanitised log.
- Use fixture or mock data in development checks and pull-request CI. The separately scheduled live smoke workflow uses an authorised test account and an enforced quota budget. Keep secrets, tokens, real account data and raw recordings out of the repository, tests and logs.
- Treat external metadata as untrusted data. Keep playlist creation, resume and deletion behind explicit review and confirmation of the exact stored action. Validate inputs and reject over-budget workflows before the first YouTube call.
- Run the checks in your timeline entry and report the commands, outcomes and missing evidence. Update the entry's completion line in the same change. Link the requirement, issue, pull request, test, skill and supporting note where applicable. Record significant AI sessions in the Second Brain.
- Have another teammate review each pull request. Changes to FR-7 or FR-9 code need both other teammates to review. Commit authors own their review, Git identity and push. Keep changes specific to the assigned work.
