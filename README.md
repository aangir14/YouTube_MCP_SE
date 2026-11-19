# YouTube_MCP_SE

FocusList is the team's local Model Context Protocol (MCP) server project for YouTube discovery, account analytics and constrained playlist creation. It uses the official YouTube Data API for live access. The learner reviews the exact playlist proposal and explicitly approves it before creation.

- [Project statement](Project_1_YouTube_MCP.pdf)
- [Condensed software requirements specification](FocusList_SRS_Condensed.docx)
- [Implementation and commit plan](FocusList_Commit_Plan.md)
- [Repository instructions](AGENTS.md)

The implementation timeline starts with requirements and design. The package setup and executable commands are added in C07. Use synthetic fixtures and mocks as the default for development and pull-request checks. Keep live credentials and raw recordings local. The example environment file contains development placeholders.

Repository setup is tracked in C01. The repository owner verifies collaborator access, the four stage milestones, and the review and merge settings for `main`. Work is reviewed through pull requests. FR-7 and FR-9 code changes require both teammates to review.
