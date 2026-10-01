# Research workflows and experimental design

Academy teaches a repeatable loop: prepare identifiable samples, test a defined property, then decide what to change. This is a useful learning model, not a claim that all materials research consists only of three operations. Sample history, controls, uncertainty and provenance connect the stages.

## Implemented scope

- A manually curated initial marketplace of six primary research papers. Source links, year, original platform, preparation, measurement and decision method are shown for each case.
- Search and domain filtering, paper details, and adaptation into a learner-owned design brief.
- Discovery studio with method composition, a gantry concept explorer and an illustrative sample-to-result exercise.
- Versioned, owner-scoped design notebooks on the existing SQLite/DynamoDB store. Up to 20 briefs, bounded inputs. Briefs are `design_only`; they cannot be submitted as execution sessions.
- Connector explorer with four modules and a curated map of committed source, pinned to opentrons-flex commit 2a9c3004400325d7816c80065a2282a4ad6b5b70. Excerpts and exact references are in briefs/connector-source.json.

## Evidence and curation

The marketplace is a curated collection, not a live web search engine or automatic paper ingestion service. Paper text is summarized in original words; figures are not copied. Diagrams are original conceptual illustrations. Academy adaptation suggestions are editorial hypotheses, not demonstrations on Flex. No paper recipe is directly executable from the marketplace.

Sources were checked on 2026-10-01. Each item in frontend discoveryContent.ts includes the primary paper, DOI, platform and a source note. The A-Lab article has a 2026 author correction; no original performance totals are repeated. The sonochemical study is a screening workflow, not automatically a closed-loop optimizer.

Future ingestion should retain DOI, publication/correction version, method evidence, equipment mapping and a human-reviewed adaptation before publishing a card. A search hit alone is not an executable protocol. No recurring crawler or paid external service is enabled.

## Runtime boundary

A brief specifies objective, variables, measurement, next-step decision, controls, method order and gantry concept. To become runnable it still needs concrete units, validated labware/material compatibility, device capabilities, calibration, motion constraints and a qualified execution plan. The existing teaching exercise and future Ubuntu Matterix gateway remain distinct execution paths. Connector diagrams do not send commands or display live device telemetry.

## Developer views in Connector Explorer

API ↔ SiLA mapping compares six source-grounded capabilities: aspiration parameters/units, motion types/defaults, temperature completion semantics, observable state and missing values, composed transfer operations, and defined error translation. Each mapping has selectable dimensions, implementation excerpts and a scenario question. The native column describes calls made by this connector; it is not a copied vendor SDK implementation. The custom Feature identifiers do not claim cross-vendor semantic equivalence.

Build a connector distinguishes SDK, HTTP and message-protocol access, then teaches six development steps with inspectable deliverables and committed code/test references. HTTP and protocol traces are generic teaching patterns, not added transports. Source links demonstrate the development structure; visiting the tutorial is not execution, test acceptance or deployment. Developer tabs have refreshable hash URLs. The 12 additional snippets are pinned in `briefs/connector-development-source.json`.
