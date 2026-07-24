# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""Factbook lifecycle meta-rules renderer (L2 only).

Single source of truth for the <factbook-lifecycle-meta> block rendered at
the tail of every emitted factbook file. Vendor-aware framing:
  - claude   → raw XML (no fence; Claude parses XML natively)
  - copilot  → markdown with ```xml fence
  - cursor   → same as copilot
  - kiro     → same as copilot/cursor (frontmatter belongs to the factbook
               file, not to meta-rules)

The canonical XML is INLINED as _META_XML_V1_1 so this module ships without
a filesystem dependency (required for OSS `nora` distribution where the
`docs/` directory may not be present). The demo file at
`docs/demos/copilot-instructions.living-v1.1.md` is the DEV-AUTHORING
surface — edits there propagate here via `make regen-meta-rules` (or hand).

Drift protection:
  - META_CONSTANT_SHA256 hashes _META_XML_V1_1 at module load
  - test_meta_rules.py asserts this equals META_CONSTANT_SHA256_PIN
  - A separate test also verifies (when demo file exists) that it matches
    the inlined constant verbatim.

Decision provenance:
  - docs/NORA-LIVING-FACTBOOK-PE-DECISIONS-APR-18-2026.md Amendment A rev 2
  - docs/NORA-HARNESS-STRATEGY-AND-BACKLOG-APR-18-2026.md Part B.1
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

# v1.2 (2026-04-19): adds <review-rituals> domain-typed hooks
# (coding/product/program/finance/legal) so the target AI knows which
# review ritual to invoke when acting on a fact. v1.1 behavior is
# preserved as the lifecycle portion; rituals are additive.
META_VERSION = "1.2"
META_VERSION_LEGACY = "1.1"  # still callable for back-compat during rollout

Target = Literal["claude", "copilot", "cursor", "kiro"]
_VALID_TARGETS = ("claude", "copilot", "cursor", "kiro")
Domain = Literal["coding", "product", "program", "finance", "legal", "other"]
DOMAINS: tuple[Domain, ...] = ("coding", "product", "program", "finance", "legal", "other")


# ─── Canonical XML (inlined — ships with module, no filesystem dep) ─────────

_META_XML_V1_1 = """<factbook-lifecycle-meta version="1.1" mode="suggest-and-auto-add">

  <purpose>
    During AI sessions where this factbook is in context, actively help maintain
    it: observe durable rules (including descriptive-convention statements),
    flag staleness, auto-add HIGH-confidence rules, and surface MEDIUM-confidence
    rules for user approval.
  </purpose>

  <observe>
    Watch user messages for DURABLE RULE signals. Three trigger families:

    (1) IMPERATIVE phrasing:
      - "always X", "never X", "must X", "don't ever X"
      - "add this as a rule", "remember this", "from now on"

    (2) DECLARATIVE-CONVENTION phrasing (new in v1.1 — do not ignore):
      - "we [verb] X" / "we [verb] X to handle Y"
        (e.g., "we wrap paid endpoints with withCreditDeduction")
      - "the existing ones all do this" / "all existing X do Y"
      - "our pattern is X" / "our convention is X"
      - "that's how we do X here" / "this is how we handle X"
      - "all [noun] use/have/call X"
      - "we typically [verb]" / "we usually [verb]"
      → These describe existing conventions the user is asking the AI to follow.
        They are durable rules even if not phrased as imperatives. Surface as
        MEDIUM by default; escalate to HIGH if user adds "always" or cites
        failure mode ("otherwise X breaks").

    (3) CORRECTION phrasing that references repeated patterns:
      - "we keep running into X", "we had a bug where X", "last time X"
      - "I've told other AI sessions this"
      - Scope-explicit: "for all API routes, ...", "every [noun] must ..."
  </observe>

  <identify>
    DURABLE RULE candidates include (in priority order):
    - Explicit policy/preference/convention statements (imperative)
    - Descriptive-convention statements where user is asking AI to follow
      the pattern (declarative)
    - Corrections that generalize beyond the current file/feature
    - Scope-tagged expectations about categories of future work

    ONE-OFF (do NOT capture):
    - Typo corrections on a single symbol/identifier
    - Single-file bug fixes with no stated generalization
    - Pure clarifications about the current question
    - User-stated facts about current state with no behavioral expectation
      (e.g., "this file is 300 lines" — fact, not rule)
  </identify>

  <classify-confidence>
    HIGH (auto-add):
      - Explicit imperative + explicit scope
      - User says "add this as a rule" / "from now on" / "always"
      - Descriptive-convention + failure-mode citation
        ("we wrap X with Y; manual handling causes double-deduction bugs")
      - Correction cites prior incident or repeated bug

    MEDIUM (suggest):
      - Descriptive-convention without explicit imperative or failure mode
        (e.g., "we wrap paid endpoints with withCreditDeduction" — new in v1.1:
         this alone is MEDIUM, not LOW)
      - Rule implied, scope ambiguous
      - Single behavior that might generalize
      - User states a convention but only applies it in the current turn

    LOW (silent):
      - One-off fix, typo correction, pure clarification
      - Facts about current state with no behavioral expectation
      - Session-trivial (applies only to this specific file in this turn)
  </classify-confidence>

  <auto-add behavior="HIGH-confidence only">
    For HIGH-confidence rules, at the END of your response:

    ✅ FACTBOOK UPDATED (auto-added, HIGH confidence)
    Rule: <concise imperative>
    Scope: <project | files:<glob> | language:<lang> | tool:<name>>
    This rule is LIVE for the rest of this session.
    Undo: reply "undo factbook" within 60 seconds, or "edit: <new wording>"

    [If Copilot cannot write files, replace this block with the SUGGEST format below
    and note "(requires file write — use Suggest mode)"]
  </auto-add>

  <suggest behavior="MEDIUM-confidence only">
    For MEDIUM-confidence rules, at the END of your response:

    📌 FACTBOOK SUGGESTION
    Rule: <concise imperative>
    Scope: <project | files:<glob> | language:<lang> | tool:<name>>
    Confidence: MEDIUM
    Source: this-session correction
    Action: Reply "add", "edit: <new wording>", or "skip"
  </suggest>

  <silent behavior="LOW-confidence">
    Stay silent — do not surface low-confidence one-offs.
  </silent>

  <staleness-check>
    If you notice an existing factbook rule that:
    - Contradicts the code you're currently seeing
    - References a file/function/concept that no longer exists
    - Has behavioral evidence of non-applicability

    at the END of your response:

    ⚠ FACTBOOK STALENESS CHECK
    Rule: <quote or ID>
    Concern: <why it may be stale>
    Evidence: <what you saw>
    Action: Reply "keep", "update: <new wording>", or "remove"
  </staleness-check>

  <dedupe>
    Before surfacing SUGGESTION or AUTO-ADD, check if the factbook already
    contains a semantically equivalent rule. If yes, stay silent — or, if
    the new phrasing is genuinely stronger, propose an UPDATE only.
  </dedupe>

  <scope-tagging>
    Every suggested/added rule MUST include scope:
    - project = whole project
    - files:<glob> = matching files only (e.g., files:src/api/**/*.ts)
    - language:<lang> = only that language
    - tool:<name> = only when using that tool
    If ambiguous, ASK the user before suggesting.
  </scope-tagging>

  <restraint>
    - Max 1 FACTBOOK SUGGESTION or AUTO-ADD per response
    - Max 1 STALENESS CHECK per response
    - Never surface in the first turn of a session (need work context first)
    - Never surface after pure clarifications or acknowledgments
    - Never propose rules that are session-trivial
  </restraint>

  <live-reload>
    When a rule is added (via auto-add or approved suggestion), treat it as
    active context for all subsequent turns in this session. Reference newly-
    added rules alongside pre-existing factbook content. The factbook is a
    LIVING document.
  </live-reload>

  <undo-semantics>
    If user replies "undo factbook" within the turn immediately following an
    AUTO-ADD, treat the rule as removed (do not apply it going forward).
    If user replies "edit: <wording>", replace the rule with the edited text.
  </undo-semantics>

</factbook-lifecycle-meta>"""


# SHA-256 of the inlined v1.1 constant. Drift test asserts this equals
# META_CONSTANT_SHA256_PIN_V1_1. To update: edit _META_XML_V1_1, run the
# test, copy the new hash into _PIN below.
META_CONSTANT_SHA256_PIN = "12c97016180678d7920198994d8cc8c25a07e300d330a71fff0647ff7f364b42"
# Retained as alias while older callers reference the short name; new code
# should use META_CONSTANT_SHA256_PIN_V1_1 + META_CONSTANT_SHA256_PIN_V1_2.
META_CONSTANT_SHA256_PIN_V1_1 = META_CONSTANT_SHA256_PIN


# v1.2 XML = v1.1 body + additive <review-rituals> block. The lifecycle
# portion (observe / identify / classify / auto-add / suggest / …) is
# unchanged, so any v1.1-aware AI still reads it correctly; the review
# rituals are additional guidance conditioned on the fact's `domain`.
_REVIEW_RITUALS_V1_2 = """

  <review-rituals version="1.2">
    Before the AI assistant acts on a fact from this factbook, it should
    determine the fact's domain (from the fact's `domain` field, or from
    the task context if the fact is untagged) and invoke the matching
    ritual IF APPLICABLE. If the domain cannot be determined, ASK the
    user before applying a ritual.

    <domain name="coding" applies-when="fact.domain=coding OR task touches code/config/tests/infra">
      <ritual name="pe-code-review" priority="high" trigger="proposing code change >30 LOC OR touching tests/DB/security/auth">
        Run a 4-tier review:
        CRITICAL — security, data integrity, compliance
        HIGH     — correctness, idempotency, error handling
        MEDIUM   — performance, UX, accessibility
        LOW      — style, naming, hygiene
        For each finding cite file:line + severity. Block on CRITICAL; fix HIGH pre-commit.
      </ritual>
      <ritual name="regression-tests" priority="high" trigger="code change complete">
        Run the FULL test suite (not just files you touched). Compare pass count to
        baseline (last green commit). Investigate new failures BEFORE declaring done.
      </ritual>
      <ritual name="coe-root-cause" priority="medium" trigger="bug fix OR incident postmortem">
        5 whys. Distinguish proximate vs root cause. Record impact, detection time,
        fix time, preventive measures. Link as fact_type=incident in the factbook.
      </ritual>
    </domain>

    <domain name="product" applies-when="fact.domain=product OR task involves PRD/RFC/roadmap/OKRs/launch">
      <ritual name="prfaq-clarity" priority="high" trigger="proposing new feature OR initiative">
        Write (or review): customer headline, problem, one-line solution, what's different,
        customer quote. If any section reads as internal-speak, rewrite for the customer.
      </ritual>
      <ritual name="risk-register" priority="high" trigger="feature scoping OR launch planning">
        Enumerate risks: technical, market, regulatory, dependency. For each:
        likelihood × impact → mitigation owner + trigger condition.
      </ritual>
      <ritual name="stakeholder-raci" priority="medium" trigger="change affects >1 team OR customer-visible">
        Map stakeholders (exec, eng, sales, support, legal). For each assign R/A/C/I.
        Flag any 'A' slot with owner=null.
      </ritual>
    </domain>

    <domain name="program" applies-when="fact.domain=program OR task involves multi-team plan/dependency/milestone">
      <ritual name="dependency-map" priority="high" trigger="milestone planning OR re-plan">
        List upstream deps (what we need) + downstream (who needs us). Flag any with
        owner=null, ETA=TBD, or cross-team coupling without a shared doc.
      </ritual>
      <ritual name="critical-path" priority="high" trigger="timeline question OR slip risk">
        Identify the longest chain of dependencies. Any critical-path task with slip >1d
        = escalate. State the buffer you have before committing a new date.
      </ritual>
      <ritual name="escalation-protocol" priority="medium" trigger="blocker identified">
        Document BEFORE the clock starts: who owns, by when, if no resolution by X
        escalate to Y. Record the blocker's first-detected timestamp.
      </ritual>
    </domain>

    <domain name="finance" applies-when="fact.domain=finance OR task involves financial data / controls / audits">
      <ritual name="reconciliation" priority="critical" trigger="any transaction summary OR balance claim">
        Source-of-truth count vs derived count. If mismatched, STOP and investigate
        before proceeding. Do not 'round' or 'approximate' when sources disagree.
      </ritual>
      <ritual name="controls-test" priority="high" trigger="new transaction type OR policy change">
        Verify segregation of duties, dual-approval, audit trail, data retention.
        Link to regulatory requirement by name (SOX §404, GAAP ASC 606, GDPR Art. 5, etc.).
      </ritual>
      <ritual name="materiality" priority="medium" trigger="dollar figure OR percentage claim in output">
        State the materiality threshold. Below → summarize. Above → itemize with source.
        Never embed a figure without a citable source.
      </ritual>
    </domain>

    <domain name="legal" applies-when="fact.domain=legal OR task involves contracts / compliance / regulation">
      <ritual name="citation-check" priority="critical" trigger="asserting law, precedent, or regulation">
        Cite jurisdiction, statute/case number, publication date. If the citation was
        AI-generated and not verified against primary source, flag it as UNVERIFIED —
        do not treat as authoritative.
      </ritual>
      <ritual name="redline-review" priority="high" trigger="contract change OR policy edit">
        Show before/after with intent. Flag any change affecting: liability, indemnity,
        IP, termination, dispute resolution, governing law, confidentiality.
      </ritual>
      <ritual name="jurisdiction-scoping" priority="medium" trigger="statement of applicability">
        State explicitly which jurisdiction applies. Default: do NOT extrapolate to
        other jurisdictions without a fresh check.
      </ritual>
    </domain>

    <fallback applies-when="domain cannot be determined from fact or task">
      ASK the user: "Which domain is this in — coding, product, program, finance,
      legal, or other?" before invoking any ritual. Never guess.
    </fallback>
  </review-rituals>"""


def _build_v1_2_xml() -> str:
    """Compose v1.2 by injecting the review-rituals block into v1.1 before
    the closing </factbook-lifecycle-meta> tag. Kept deterministic so the
    SHA-256 pin stays stable as long as both source strings are stable."""
    insert_before = "</factbook-lifecycle-meta>"
    idx = _META_XML_V1_1.rfind(insert_before)
    if idx < 0:
        raise RuntimeError(
            "v1.1 constant lost its closing tag — drift; regenerate from source."
        )
    body = _META_XML_V1_1[:idx] + _REVIEW_RITUALS_V1_2 + "\n\n" + _META_XML_V1_1[idx:]
    # Bump the version attribute in the opening tag
    return body.replace(
        '<factbook-lifecycle-meta version="1.1"',
        '<factbook-lifecycle-meta version="1.2"',
        1,
    )


_META_XML_V1_2 = _build_v1_2_xml()

# v1.2 drift-pin. On any v1.2 text change run test_meta_rules; copy the
# fresh hash into _V1_2 below.
META_CONSTANT_SHA256_PIN_V1_2 = (
    "22b251faa4901002c0db466ab23dbad2e05101ccb0141bbb619637b958ae9cb1"
)


def compute_constant_sha256(version: str = META_VERSION_LEGACY) -> str:
    """SHA-256 of the inlined v1.1 or v1.2 XML constant."""
    if version == "1.2":
        return hashlib.sha256(_META_XML_V1_2.encode("utf-8")).hexdigest()
    return hashlib.sha256(_META_XML_V1_1.encode("utf-8")).hexdigest()


def _framing_header(version: str = META_VERSION) -> str:
    return (
        f"## Factbook Lifecycle Meta-Rules (LIVING FACTBOOK — v{version})\n\n"
        "The AI assistant with this factbook in context **must** follow these "
        "lifecycle instructions in addition to answering the user's question.\n\n"
    )


def _body_for_version(version: str) -> str:
    if version == "1.1":
        return _META_XML_V1_1
    if version == "1.2":
        return _META_XML_V1_2
    raise ValueError(
        f"unknown meta-rules version: {version!r}; supported: 1.1, 1.2"
    )


def render(target: Target, version: str = META_VERSION) -> str:
    """Return the L2 lifecycle meta-rules block framed for the target.

    Args:
        target: one of "claude", "copilot", "cursor", "kiro".
        version: "1.1" (lifecycle only) or "1.2" (lifecycle + review-rituals).

    Returns:
        Ready-to-append string.
        For claude: header + raw XML (Claude parses XML natively, no fence tax).
        For copilot/cursor/kiro: header + ```xml-fenced XML.

    Raises:
        ValueError on unknown target or unknown version.
    """
    xml_body = _body_for_version(version)
    if target not in _VALID_TARGETS:
        raise ValueError(
            f"unknown target: {target!r}; supported: {', '.join(_VALID_TARGETS)}"
        )

    header = _framing_header(version)
    if target == "claude":
        return header + xml_body
    return header + f"```xml\n{xml_body}\n```"


# ─── Dev-only: verify demo file matches inlined constant ───────────────────


def _resolve_demo_path() -> Path | None:
    """Find the dev-authoring demo file, if present in this checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "docs" / "demos" / "copilot-instructions.living-v1.1.md",
        here.parent / "docs" / "demos" / "copilot-instructions.living-v1.1.md",
        here.parent.parent / "docs" / "demos" / "copilot-instructions.living-v1.1.md",
    ):
        if candidate.exists():
            return candidate
    return None


def demo_file_matches_constant() -> tuple[bool, str]:
    """Verify the dev demo file's XML matches the inlined constant.

    Returns (True, "") if match, (False, reason) if drift or missing.
    Used by test_meta_rules.py — NOT called from render() (runtime-cheap).
    """
    path = _resolve_demo_path()
    if path is None:
        return False, "demo file not found in checkout"
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"(<factbook-lifecycle-meta\b[^>]*>.*?</factbook-lifecycle-meta>)",
        text,
        re.DOTALL,
    )
    if not m:
        return False, f"no <factbook-lifecycle-meta> block in {path}"
    demo_xml = m.group(1)
    if demo_xml == _META_XML_V1_1:
        return True, ""
    return False, (
        "demo file XML differs from inlined _META_XML_V1_1; "
        "either update the pin or regenerate the demo file"
    )


if __name__ == "__main__":
    import sys
    print(f"META_VERSION: {META_VERSION}")
    print(f"constant SHA-256 (actual): {compute_constant_sha256()}")
    print(f"constant SHA-256 (pinned): {META_CONSTANT_SHA256_PIN}")
    if compute_constant_sha256() != META_CONSTANT_SHA256_PIN:
        print("⚠ Drift — update META_CONSTANT_SHA256_PIN in meta_rules.py", file=sys.stderr)
    ok, reason = demo_file_matches_constant()
    print(f"demo file match: {ok}" + (f" ({reason})" if reason else ""))
    for t in _VALID_TARGETS:
        body = render(t)
        print(f"{t:>8s}: {len(body):5d} chars")
