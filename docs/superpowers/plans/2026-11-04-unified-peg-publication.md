# Unified Stockscreener and PEG Publication Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Each worker owns distinct files; root deploys through n8n only.

**Goal:** One Stockscreener n8n workflow produces one coherent release containing current-session screening and recomputed PEG, with numerical explanations for every unavailable PEG.

**Architecture:** Prepare a frozen candidate using current official market data and latest disclosed financials. Inside the same n8n workflow, search missing evidence from that candidate using private SearXNG with Brave fallback. Finalize the exact frozen candidate, recompute PEG, build all public artifacts, then publish once. The previous post-publication child hook is removed. Publication proof, Notion archive, cache, recovery and schedules remain integrated.

**Tech Stack:** Existing n8n native nodes, Python pipeline, GitHub Actions, React/TypeScript and Cloudflare deployment. No runtime AI.

## Task 1: Explicit PEG diagnostics
- [ ] Add failing tests for nonpositive current/prior EPS, falling/flat growth, missing evidence and source dates.
- [ ] Extend pipeline/peg_ttm.py diagnostics with current/prior EPS, growth when meaningful, cutoff and source evidence dates.
- [ ] Extend src/domain/types.ts and API validator; render concrete reasons and numerical evidence in PegReviewSection and StrategyCard.
- [ ] Run backend/frontend targeted tests. Never fabricate EPS or growth for incomplete/incomparable evidence.

## Task 2: Candidate preparation and finalization
- [ ] Add failing tests for no publication from prepare, candidate identity/date/hash mismatch, bounded archive extraction and stale PEG removal.
- [ ] Extend daily.yml with prepare_peg and finalize_peg modes. Prepare uploads exact-run candidate and preview, with no Git commit/publication.
- [ ] Finalize consumes prepare_run_id, prepare_run_attempt, candidate_sha256, search_manifest_commit, with exact request/date correlation. Recompute every PEG, export, fingerprint, archive, cache and review from one final generation before the only publication.
- [ ] Preserve institutional_probe and ownership_recompute behavior; run targeted pipeline and workflow tests.

## Task 3: One n8n workflow
- [ ] Back up current live graph and preserve schedule/settings/credential references.
- [ ] Add failing orchestration tests for prepare, exact artifact retrieval, source discovery, finalize and recovery without duplicate dispatch.
- [ ] Inline PEG source nodes in main; use current candidate roster/reasons, private SearXNG URL from Data Table and bounded Brave usage.
- [ ] Remove asynchronous post-publication PEG child hook. Continue existing final artifact, website, Notion and cache verification only after finalization.
- [ ] Validate generated graph and test recovery, lease/CAS conflicts and unavailable-source release without stale PEG.

## Task 4: Review and delivery
- [ ] Independently review changes for requirement coverage and security.
- [ ] Run relevant Python, JS, frontend and build checks; inspect actual scope of evidence.
- [ ] Publish source through n8n GitHub credentials only, wait for CI and deploy.
- [ ] Update/publish main n8n graph after source compatibility is proven; disable old standalone PEG publisher.
- [ ] Run one end-to-end update for latest completed session, inspect public same-generation dates/numbers/reasons, archive temporary tooling.
- [ ] Record evidence and remaining next-schedule verification without claiming an unobserved schedule passed.

## Integration findings and required corrections

The first source release (`46c90f0e7c4a430c45559b3a96b94ecb022ec2d9`) passed CI and Cloudflare deployment. Manual execution 1500 reached authenticated prepare Actions run 41766156514, but candidate creation exceeded 64 MiB because it included historical releases and archives. No public data was published. Candidate packing now selects the current generation and referenced current receipts; final restore preserves existing history. The main workflow was unpublished at that checkpoint; restoring its schedule requires a successful corrected end-to-end test.

A further freshness audit found that the legacy FinMind gap planner could wait for the ordinary filing deadline and skip early reports for an otherwise complete EPS history. Bounded daily early-filing probes now cover that gap. Actual income-statement source-check receipts distinguish fresh financial lookups from newer quote/revenue requests. Calendar quarters guide discovery; they do not prove a report has been filed. Known newer eligible statements without EPS and unverified cached-only financials cannot produce a displayed PEG.

The top-level PEG review proof is rebuilt from the exact final export for every publishing mode, including ownership-only revisions. This keeps review, export and latest-generation identities consistent after subsequent updates.
