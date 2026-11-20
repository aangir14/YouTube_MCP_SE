---
title: Project Licensing Evaluation, Third-Party Compliance, and TBD-5 Tracking
author: Aangir Doshi
date: 2026-11-19
type: decision-record
status: draft
srs_ids:
  - L-1
  - L-2
  - L-3
  - L-4
  - L-5
  - L-6
  - TBD-5
sources:
  - "https://opensource.org/licenses/MIT"
  - "https://www.apache.org/licenses/LICENSE-2.0"
  - "https://developers.google.com/youtube/terms/developer-policies"
  - "FocusList_SRS_Condensed.docx Section 6.3 & Appendix C (TBD-5)"
evidence:
  - "FocusList_Commit_Plan.md#7-decisions-carried-forward-from-appendix-c"
uncertainty:
  - "TBD-5: Final team selection between MIT and Apache 2.0 license subject to course staff evaluation guidelines"
  - "Third-party license consolidation location (docs/licenses/ vs root LICENSES/)"
---

# Project Licensing Evaluation, Third-Party Compliance, and TBD-5 Tracking

## 1. Context and Objective

Under **SRS Section 6.3 (Legal, Policy and Compliance Requirements)** and **TBD-5**, the FocusList project must record its open-source repository license decision, verify compatibility with external platform terms (YouTube Developer Policies and Branding Guidelines), and document the location of third-party dependency licenses.

---

## 2. Repository License Candidate Evaluation (TBD-5)

As of C04, no single license decision was mandated in the project statement (`Project_1_YouTube_MCP.pdf`). The primary candidates under consideration are:

| License | Grant & Permissions | Patents & Trademarks | Compatibility | Evaluation for FocusList |
| :--- | :--- | :--- | :--- | :--- |
| **MIT License** | Highly permissive; simple 1-page text; commercial and academic use allowed. | Silent on express patent grant; standard warranty disclaimer. | Compatible with all contemplated libraries and MCP ecosystem. | **Strong Candidate**: Lightweight, standard for MCP open-source tools, minimal friction for educational and developer reuse. |
| **Apache License 2.0** | Permissive with explicit copyright grant. | Express patent grant and termination clause; explicit trademark restrictions. | Compatible with Google API client libraries (which are Apache 2.0). | **Strong Candidate**: Robust legal protections, explicit patent safety, aligns with Google developer platform conventions. |
| **Academic / Educational Only** | Restricts usage strictly to course evaluation. | Varies. | Inhibits broader open-source distribution and portfolio reuse. | **Not Recommended**: Restricts public demonstration of the student project. |

---

## 3. Third-Party Licenses and Dependency Boundaries

FocusList integrates the following key third-party ecosystems, all of which use permissive open-source licenses:

1. **Google API Client Libraries (`google-api-python-client`, `google-auth`)**:
   - License: **Apache License 2.0**
   - Compliance: Apache 2.0 requires preservation of copyright notices and attribution.
2. **Model Context Protocol Python SDK (`mcp`)**:
   - License: **MIT License**
   - Compliance: Standard MIT attribution notice.
3. **Pydantic, Typer, and FastMCP Ecosystem**:
   - License: **MIT License**
4. **SQLite 3**:
   - License: **Public Domain (Blessing)**

### Third-Party License Record Location
Third-party license notices, dependency manifests (`requirements.txt`, `pyproject.toml`), and upstream copyright notices will be maintained under:
`docs/licenses/` (with a root `LICENSE` file tracking the project's primary license).

---

## 4. YouTube API Terms and Branding Constraints (L-1 to L-6)

Regardless of software license, FocusList must adhere to the **YouTube API Services Developer Policies**:
1. **Non-Endorsement**: FocusList must not imply official endorsement, sponsorship, or affiliation with Google or YouTube. A prominent non-endorsement statement must appear in `README.md` and the User Guide (**L-1**, **BR-11**).
2. **Proper Attribution**: When YouTube videos or channels are displayed, canonical YouTube logos and styling must comply with YouTube Branding Guidelines.
3. **No Unofficial Access**: No scraping, transcript extraction, or bypassing of official YouTube Data API v3 endpoints is permitted (**L-2**).

---

## 5. TBD-5 Open Decision Status and Next Steps

- **Item**: TBD-5 (Repository Licence)
- **Assigned Owner**: Aangir Doshi
- **Current Status**: **Open / Documented Baseline**
- **Next Step**: Review MIT vs Apache 2.0 with team members (Harshil and Ayush) during Stage 1 requirements close (C06) and Stage 2 kickoff. Confirm publication and place license file at project root prior to release verification in **C36**.
