# -*- coding: utf-8 -*-
"""
SunBiz Funding - AI Ad Copy Generator
=======================================
Generates MCA-compliant ad copy for SunBiz Funding campaigns.

Primary path:  Claude (Anthropic Messages API via ANTHROPIC_API_KEY) — generative copy.
Fallback path: Gemini API (via GEMINI_API_KEY), then built-in template banks
               (no API key required, always works).

Compliance rules enforced on ALL output:
  - Forbidden: "loan", "MCA", "merchant cash advance", "guaranteed approval",
               "hard credit pull", "guarantee", "guaranteed"
  - Required CTAs: "See if you qualify", "Apply now", "Check your options"
  - Amounts always preceded by "up to"
  - No unlicensed claims about approval rates or timelines

Campaign types:
  growth_capital, consolidation, fast_funding, industry, social_proof

Usage:
    from scripts.ad_copy_generator import AdCopyGenerator

    gen = AdCopyGenerator()
    copy = gen.generate_ad_copy("growth_capital", tone="confident", num_variations=3)
    print(gen.validate_compliance(copy[0]["headline"]))
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

# Ensure UTF-8 output on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ad_copy_generator")

# ---------------------------------------------------------------------------
# Credential loading — same pattern as meta_ads_engine.py
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env.agents"


def _load_env_agents() -> dict[str, str]:
    """
    Parse KEY=VALUE pairs from .env.agents at the project root.
    Skips blank lines and comment lines.
    Returns an empty dict if the file does not exist.
    """
    if not _ENV_PATH.exists():
        log.warning(".env.agents not found at %s — API features disabled.", _ENV_PATH)
        return {}
    creds: dict[str, str] = {}
    with _ENV_PATH.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    return creds


def _claude_model() -> str:
    """Canonical Sonnet ID from the shared model registry (ad copy is
    customer-facing brand voice → Sonnet drafting tier), with the literal as a
    fallback when lib.model_registry isn't on sys.path."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
        from lib.model_registry import SONNET  # type: ignore
        return SONNET
    except Exception:
        return "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Compliance constants
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bloan\b", '"loan" — use "funding", "advance", or "capital"'),
    (r"\bMCA\b", '"MCA" — use "working capital" or "business funding"'),
    (r"merchant\s+cash\s+advance", '"merchant cash advance" — use "business advance" or "funding"'),
    (r"guaranteed\s+approval", '"guaranteed approval" — use "See if you qualify"'),
    (r"hard\s+credit\s+pull", '"hard credit pull" — use "no credit pull"'),
    (r"\bguarantee[sd]?\b", '"guarantee" — remove or replace with "may qualify"'),
    (r"100\s*%\s*approv", '"100% approval" — not permitted'),
    (r"no\s+credit\s+check", '"no credit check" — use "no credit pull"'),
    (r"\binstant\s+approv", '"instant approval" — use "fast decision" or "quick review"'),
]

_COMPLIANT_CTAS = [
    "See if you qualify",
    "Apply now",
    "Check your options",
    "Get started today",
    "Find out if you qualify",
]

# ---------------------------------------------------------------------------
# Template banks — 10+ headlines and descriptions per campaign type
# ---------------------------------------------------------------------------

_TEMPLATE_BANKS: dict[str, dict[str, list[str]]] = {
    "growth_capital": {
        "headlines": [
            "Grow Your Business with Working Capital",
            "Up to $500K in Business Funding — Apply Today",
            "Your Business Deserves Better Capital",
            "Scale Faster with Private Lending Solutions",
            "Working Capital for Ambitious Business Owners",
            "Unlock Up to $500K for Your Business",
            "Business Funding Designed Around You",
            "Stop Waiting — Access Capital Today",
            "Fuel Your Growth with Business Funding",
            "More Capital. More Opportunity. Apply Now.",
            "Business Funding Without the Banker's Red Tape",
            "Your Next Level Starts with Working Capital",
        ],
        "descriptions": [
            "SunBiz Funding provides working capital to help your business reach its potential. See if you qualify — no credit pull required.",
            "We partner with business owners to unlock funding when traditional options fall short. Check your options in minutes.",
            "Up to $500K in business capital with flexible terms. Our advisors find the right fit for your business — apply now.",
            "From inventory to expansion, get the working capital you need to move forward. Find out if you qualify today.",
            "SunBiz Funding works with businesses across every industry. Discover your funding options with no obligation.",
            "Private lending solutions tailored to your business revenue — not just your credit score. See if you qualify.",
            "Fast decisions, flexible terms, and a team that understands business. Get started with SunBiz Funding today.",
            "Your revenue is your strength. Access working capital based on your business performance. Apply now.",
            "Stop letting cash flow hold your business back. SunBiz Funding has working capital solutions ready for you.",
            "Business funding from a partner who puts your success first. Check your options — it takes 60 seconds.",
        ],
        "messages": [
            "Ready to take your business to the next level? SunBiz Funding offers working capital solutions for growth-focused owners.",
            "Business growth doesn't wait. Neither should you. See if you qualify for up to $500K in funding — apply today.",
        ],
    },
    "consolidation": {
        "headlines": [
            "One Simple Payment Instead of Many",
            "Consolidate Your Business Advances Today",
            "Simplify Your Business Cash Flow",
            "Stop Juggling Multiple Daily Payments",
            "One Advance. One Payment. More Peace of Mind.",
            "Restructure Your Business Debt — See If You Qualify",
            "Tired of Multiple Advance Payments? We Can Help.",
            "Consolidate & Get Back to Running Your Business",
            "Fewer Payments. Better Cash Flow. Apply Now.",
            "Business Debt Consolidation — SunBiz Funding",
            "Regain Control of Your Business Finances",
            "Consolidation Solutions for Business Owners",
        ],
        "descriptions": [
            "Managing multiple daily advance payments? SunBiz Funding can consolidate them into one manageable payment. See if you qualify.",
            "Stop letting stacked advances drain your cash flow. Our consolidation solutions help you breathe again — apply now.",
            "One advance, one payment, one trusted partner. SunBiz Funding restructures your obligations so you can focus on growth.",
            "Our advisors specialize in business advance consolidation. Find out if you qualify for a restructured solution today.",
            "Multiple daily payments hurting your cash flow? We offer consolidation options that work with your business revenue.",
            "SunBiz Funding helps business owners simplify their finances. Check your consolidation options — no obligation.",
            "Regain financial clarity. Consolidate your business advances with a partner who understands your industry.",
            "Less complexity, better cash flow management. See if SunBiz Funding's consolidation solutions are right for you.",
            "Our team works directly with your business to find a consolidation path that actually makes sense. Apply now.",
            "You built your business — don't let stacked payments slow you down. Consolidate with SunBiz Funding today.",
        ],
        "messages": [
            "Multiple advances stacking up? SunBiz Funding offers consolidation solutions to help you regain cash flow control.",
            "Simplify your business finances with one consolidated payment. Our advisors are ready to find the right fit for you.",
        ],
    },
    "fast_funding": {
        "headlines": [
            "Business Capital — Fast Decisions",
            "Don't Wait Weeks — Get Funded Faster",
            "Quick Working Capital for Your Business",
            "Fast Business Funding — Apply in Minutes",
            "Your Business Needs Capital Now. We Move Fast.",
            "Same-Week Business Funding — See If You Qualify",
            "Speed Matters — Fast Business Capital Solutions",
            "Quick Access to Business Capital",
            "Decisions in Hours, Not Weeks",
            "Business Funding on Your Timeline",
            "When You Need Capital Fast — SunBiz Funding",
            "Fast, Flexible Business Funding Solutions",
        ],
        "descriptions": [
            "When your business opportunity can't wait, SunBiz Funding delivers fast decisions on working capital. Apply now.",
            "Traditional banks take weeks. SunBiz Funding moves faster. See if you qualify for business capital today.",
            "Fast decisions, same-week funding potential. Check your options with SunBiz Funding — no credit pull required.",
            "Your business moves at the speed of your decisions. Get working capital that keeps up — apply now.",
            "Up to $500K in business funding with fast turnaround. Our advisors are ready to help — see if you qualify.",
            "Speed and reliability. SunBiz Funding provides fast business capital decisions from a team you can trust.",
            "Don't let slow funding kill a good opportunity. SunBiz Funding has working capital solutions ready for you.",
            "Fast, flexible, and focused on your business. Check your funding options with SunBiz Funding today.",
            "From application to decision — our process is built for speed without sacrificing service. Apply now.",
            "Same-week business capital for qualified businesses. Find out if you qualify with no obligation.",
        ],
        "messages": [
            "Time is money. SunBiz Funding provides fast business capital decisions so you can seize every opportunity.",
            "Fast working capital for businesses that can't afford to wait. Apply now and see your options today.",
        ],
    },
    "industry": {
        "headlines": [
            "Business Funding for Restaurant Owners",
            "Working Capital for Retail Businesses",
            "Healthcare Business Funding Solutions",
            "Construction Business Capital — Apply Now",
            "Trucking & Logistics Funding Available",
            "Manufacturing Business Capital Solutions",
            "Salon & Beauty Business Funding",
            "Auto Repair Shop Working Capital",
            "Dental Practice Funding Solutions",
            "Law Firm Working Capital — SunBiz Funding",
            "Business Funding for Service Industries",
            "Specialized Capital for Your Industry",
        ],
        "descriptions": [
            "SunBiz Funding understands your industry. We offer working capital solutions tailored to your business cycle. See if you qualify.",
            "Industry-specific funding solutions for business owners who need a lender that understands their world. Apply now.",
            "Whether you're in food service, retail, or professional services — SunBiz Funding has capital solutions for you.",
            "We work with businesses across dozens of industries. Find out if you qualify for working capital tailored to your sector.",
            "Your industry has unique cash flow needs. SunBiz Funding's advisors specialize in funding solutions that fit. Apply today.",
            "Not all businesses are the same. Our advisors match you with capital solutions designed for your specific industry.",
            "Seasonal cycles, equipment needs, payroll demands — SunBiz Funding understands your business. Check your options.",
            "Business capital that works with your revenue cycles, not against them. See if you qualify with SunBiz Funding.",
            "We've helped hundreds of business owners across your industry access working capital. Apply now and see your options.",
            "Industry knowledge meets financial expertise. SunBiz Funding is your partner in business capital. Get started today.",
        ],
        "messages": [
            "SunBiz Funding specializes in working capital for your industry. Our advisors understand your unique cash flow needs.",
            "No generic funding. SunBiz Funding provides capital solutions tailored to your specific industry and revenue model.",
        ],
    },
    "social_proof": {
        "headlines": [
            "Join Hundreds of Funded Business Owners",
            "Business Owners Trust SunBiz Funding",
            "Real Results for Real Business Owners",
            "Businesses Like Yours Are Getting Funded",
            "SunBiz Funding — Trusted by Business Owners",
            "Hundreds of Business Owners Can't Be Wrong",
            "See Why Business Owners Choose SunBiz",
            "Your Peers Are Growing with SunBiz Funding",
            "Proven Business Capital Solutions",
            "Business Owners Across the US Choose Us",
            "Results-Driven Business Funding",
            "A Partner Businesses Recommend",
        ],
        "descriptions": [
            "Hundreds of business owners have trusted SunBiz Funding for working capital. See if you qualify to join them.",
            "Business owners across the country count on SunBiz Funding for reliable, fast capital solutions. Apply now.",
            "Real businesses. Real results. SunBiz Funding has helped business owners access the capital they need to grow.",
            "When business owners need working capital, they come to SunBiz Funding. Check your options today.",
            "Our business clients come back because we deliver. See if you qualify for funding with a team you can trust.",
            "From restaurants to retail — business owners choose SunBiz Funding because we understand their needs. Apply now.",
            "Trusted by businesses across dozens of industries. SunBiz Funding is your financial growth partner.",
            "Join the growing community of business owners who've found the right capital solution with SunBiz Funding.",
            "We've built our reputation one business owner at a time. Find out how we can help you — apply today.",
            "SunBiz Funding: the business capital partner that business owners recommend to other business owners.",
        ],
        "messages": [
            "Hundreds of business owners trust SunBiz Funding for working capital. See if you qualify and join them today.",
            "Proven, trusted, and fast. SunBiz Funding delivers business capital solutions that business owners recommend.",
        ],
    },
}

# Tonal modifiers that can be injected into prompts
_TONE_DESCRIPTORS: dict[str, str] = {
    "confident": "authoritative, direct, and confident — speak to successful business owners",
    "empathetic": "warm and understanding — acknowledge the challenges business owners face",
    "urgent": "create appropriate urgency around opportunities — time-sensitive but not pushy",
    "professional": "polished and professional — financial advisor tone, not salesy",
    "conversational": "friendly and conversational — like advice from a trusted advisor",
}

# Gemini API endpoint (Flash 2.5 — fastest model available for text generation on this key)
# Model name confirmed via ListModels API; gemini-2.0-flash is no longer available to new users
_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class AdCopyVariation:
    """A single ad copy variation."""

    headline: str
    description: str
    message: str                   # longer-form post text (for Meta feed)
    cta: str
    campaign_type: str
    tone: str
    source: str                    # "gemini" or "template"


@dataclass
class ComplianceResult:
    """Result of a compliance check on ad copy text."""

    passed: bool
    violations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "PASS — no compliance violations detected."
        violation_list = "; ".join(self.violations)
        return f"FAIL — violations: {violation_list}"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class AdCopyGenerator:
    """
    AI-powered ad copy generator for SunBiz Funding.

    Generates MCA-compliant headlines, descriptions, and post copy for
    Meta Ads and Google Ads campaigns.

    Primary:  Gemini API (requires GEMINI_API_KEY in .env.agents)
    Fallback: Built-in template banks (always available)
    """

    _SUPPORTED_CAMPAIGN_TYPES = frozenset(
        ["growth_capital", "consolidation", "fast_funding", "industry", "social_proof"]
    )

    def __init__(self) -> None:
        creds = _load_env_agents()
        self._gemini_api_key: str = creds.get("GEMINI_API_KEY", "")
        self._use_gemini = bool(
            self._gemini_api_key and not self._gemini_api_key.startswith("INSERT_")
        )
        # Claude is the preferred provider — same Anthropic key + model tier as
        # the rest of the fleet. Gemini and the template banks are fallbacks.
        anthropic_key = (
            creds.get("ANTHROPIC_API_KEY") or creds.get("BRAVO_ANTHROPIC_API_KEY") or ""
        )
        self._anthropic_api_key: str = anthropic_key.strip()
        self._use_claude = bool(
            self._anthropic_api_key and not self._anthropic_api_key.startswith("INSERT_")
        )
        self._claude_model: str = _claude_model()
        # Gate for LLM-vs-template: true if either provider is configured.
        self._use_llm = self._use_claude or self._use_gemini
        self._last_provider = "template"
        if self._use_claude:
            log.info(
                "Anthropic key detected — Claude copy generation enabled (model=%s).",
                self._claude_model,
            )
        elif self._use_gemini:
            log.info("No Anthropic key; Gemini key detected — Gemini copy generation enabled.")
        else:
            log.info("No LLM key — using template banks for copy generation.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_ad_copy(
        self,
        campaign_type: str,
        tone: str = "confident",
        num_variations: int = 3,
    ) -> list[AdCopyVariation]:
        """
        Generate multiple headline + description + message variations.

        Args:
            campaign_type:  One of: growth_capital, consolidation, fast_funding,
                            industry, social_proof.
            tone:           One of: confident, empathetic, urgent, professional,
                            conversational.
            num_variations: Number of variations to return (1–10).

        Returns:
            List of AdCopyVariation objects, compliance-validated.
        """
        self._validate_campaign_type(campaign_type)
        num_variations = max(1, min(10, num_variations))

        if self._use_llm:
            return self._generate_via_gemini(campaign_type, tone, num_variations)
        return self._generate_from_templates(campaign_type, tone, num_variations)

    def generate_from_competitor(
        self,
        competitor_text: str,
        tone: str = "professional",
    ) -> list[AdCopyVariation]:
        """
        Analyze competitor ad copy and generate SunBiz-branded alternatives.

        Extracts the value proposition and emotional hook from the competitor
        text, then generates compliant SunBiz versions.

        Args:
            competitor_text: Raw competitor ad text (headline and/or description).
            tone:            Tone for the generated alternatives.

        Returns:
            List of 3 AdCopyVariation objects.
        """
        if not self._use_llm:
            log.info("Gemini not available — generating template-based alternatives.")
            return self._generate_from_templates("growth_capital", tone, 3)

        prompt = (
            "You are an expert financial services copywriter for SunBiz Funding.\n\n"
            "Analyze the following competitor ad copy and generate 3 SunBiz Funding "
            "alternatives that capture the same emotional hook and value proposition, "
            "but with SunBiz branding and strict compliance rules.\n\n"
            f"COMPETITOR AD:\n{competitor_text}\n\n"
            "COMPLIANCE RULES (non-negotiable):\n"
            "- NEVER use: loan, MCA, merchant cash advance, guaranteed approval, "
            "hard credit pull, guarantee, guaranteed\n"
            "- USE INSTEAD: funding, advance, capital, working capital, private lending\n"
            "- CTAs must be: See if you qualify / Apply now / Check your options\n"
            "- Amounts always preceded by 'up to'\n"
            "- Company: SunBiz Funding\n\n"
            "Return ONLY a JSON array with 3 objects, each with keys: "
            "headline, description, message, cta\n"
            "No markdown, no explanation — pure JSON only."
        )

        return self._call_gemini_and_parse(prompt, "growth_capital", tone, fallback_count=3)

    def generate_seasonal(
        self,
        season: str,
        campaign_type: str,
        num_variations: int = 3,
    ) -> list[AdCopyVariation]:
        """
        Generate seasonal ad copy.

        Args:
            season:        Season or time period (e.g. "Q4", "summer", "tax season",
                           "new year", "back to school").
            campaign_type: Campaign type to base the copy on.
            num_variations: Number of variations.

        Returns:
            List of AdCopyVariation objects.
        """
        self._validate_campaign_type(campaign_type)

        if not self._use_llm:
            log.info("Gemini not available — generating seasonal template variants.")
            variants = self._generate_from_templates(campaign_type, "confident", num_variations)
            # Inject season into headlines
            for v in variants:
                v.headline = f"{season.title()}: {v.headline}"
            return variants

        tone_desc = _TONE_DESCRIPTORS.get("confident", "confident and direct")
        bank = _TEMPLATE_BANKS.get(campaign_type, _TEMPLATE_BANKS["growth_capital"])
        sample_headlines = bank["headlines"][:4]

        prompt = (
            "You are an expert financial services copywriter for SunBiz Funding.\n\n"
            f"Generate {num_variations} {season}-themed ad copy variations for a "
            f"{campaign_type.replace('_', ' ')} campaign. Tone: {tone_desc}.\n\n"
            "COMPLIANCE RULES (non-negotiable):\n"
            "- NEVER use: loan, MCA, merchant cash advance, guaranteed approval, "
            "hard credit pull, guarantee, guaranteed\n"
            "- USE INSTEAD: funding, advance, capital, working capital, private lending\n"
            "- CTAs: See if you qualify / Apply now / Check your options\n"
            "- Amounts: always preceded by 'up to'\n"
            "- Company: SunBiz Funding\n\n"
            f"Reference headlines for style (do NOT copy directly):\n{sample_headlines}\n\n"
            f"Return ONLY a JSON array with {num_variations} objects, each with keys: "
            "headline, description, message, cta\n"
            "No markdown, no explanation — pure JSON only."
        )

        return self._call_gemini_and_parse(prompt, campaign_type, "confident", fallback_count=num_variations)

    def validate_compliance(self, copy_text: str) -> ComplianceResult:
        """
        Check copy text for forbidden terms and compliance violations.

        Args:
            copy_text: Any ad copy string (headline, description, or full post).

        Returns:
            ComplianceResult with passed flag, violations, and suggestions.
        """
        violations: list[str] = []
        suggestions: list[str] = []

        for pattern, description in _FORBIDDEN_PATTERNS:
            if re.search(pattern, copy_text, re.IGNORECASE):
                violations.append(f'Forbidden term: {description}')

        # Check for bare dollar amounts without "up to"
        if re.search(r"\$\d+[Kk]?\b", copy_text):
            if not re.search(r"up\s+to\s+\$\d+", copy_text, re.IGNORECASE):
                suggestions.append(
                    'Specific dollar amounts should be preceded by "up to" '
                    '(e.g. "up to $500K").'
                )

        # Check CTA presence (only flag if text is long enough to include a CTA)
        if len(copy_text) > 50:
            has_compliant_cta = any(
                cta.lower() in copy_text.lower() for cta in _COMPLIANT_CTAS
            )
            if not has_compliant_cta:
                suggestions.append(
                    'Consider adding a compliant CTA: '
                    '"See if you qualify", "Apply now", or "Check your options".'
                )

        return ComplianceResult(
            passed=len(violations) == 0,
            violations=violations,
            suggestions=suggestions,
        )

    def generate_headlines(
        self,
        campaign_type: str,
        count: int = 5,
        tone: str = "confident",
    ) -> list[str]:
        """
        Generate headlines only.

        Args:
            campaign_type: One of the supported campaign types.
            count:         Number of headlines to return.
            tone:          Desired tone.

        Returns:
            List of headline strings, compliance-validated.
        """
        self._validate_campaign_type(campaign_type)
        count = max(1, min(20, count))

        if self._use_llm:
            tone_desc = _TONE_DESCRIPTORS.get(tone, tone)
            prompt = (
                "You are a financial services copywriter for SunBiz Funding.\n\n"
                f"Generate {count} short, punchy ad headlines for a "
                f"{campaign_type.replace('_', ' ')} campaign. "
                f"Tone: {tone_desc}. Max 40 characters each.\n\n"
                "COMPLIANCE (non-negotiable):\n"
                "- No: loan, MCA, merchant cash advance, guaranteed, guarantee\n"
                "- Yes: funding, capital, advance, working capital\n"
                "- Company: SunBiz Funding\n\n"
                f"Return ONLY a JSON array of {count} headline strings. Pure JSON only."
            )
            try:
                raw = self._call_llm_raw(prompt)
                headlines: list[str] = json.loads(raw)
                if isinstance(headlines, list):
                    return [h for h in headlines if self.validate_compliance(h).passed][:count]
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Gemini headline generation failed (%s) — using templates.", exc)

        # Template fallback
        bank = _TEMPLATE_BANKS.get(campaign_type, _TEMPLATE_BANKS["growth_capital"])
        all_headlines = bank["headlines"].copy()
        random.shuffle(all_headlines)
        return [h for h in all_headlines if self.validate_compliance(h).passed][:count]

    def generate_descriptions(
        self,
        campaign_type: str,
        count: int = 5,
        tone: str = "confident",
    ) -> list[str]:
        """
        Generate descriptions only.

        Args:
            campaign_type: One of the supported campaign types.
            count:         Number of descriptions to return.
            tone:          Desired tone.

        Returns:
            List of description strings, compliance-validated.
        """
        self._validate_campaign_type(campaign_type)
        count = max(1, min(20, count))

        if self._use_llm:
            tone_desc = _TONE_DESCRIPTORS.get(tone, tone)
            prompt = (
                "You are a financial services copywriter for SunBiz Funding.\n\n"
                f"Generate {count} ad descriptions (1-2 sentences each) for a "
                f"{campaign_type.replace('_', ' ')} campaign. "
                f"Tone: {tone_desc}. Max 125 characters each.\n\n"
                "COMPLIANCE (non-negotiable):\n"
                "- No: loan, MCA, merchant cash advance, guaranteed, guarantee, hard credit pull\n"
                "- Yes: funding, capital, advance, working capital, private lending\n"
                "- CTA: end with See if you qualify / Apply now / Check your options\n"
                "- Company: SunBiz Funding\n\n"
                f"Return ONLY a JSON array of {count} description strings. Pure JSON only."
            )
            try:
                raw = self._call_llm_raw(prompt)
                descriptions: list[str] = json.loads(raw)
                if isinstance(descriptions, list):
                    return [d for d in descriptions if self.validate_compliance(d).passed][:count]
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Gemini description generation failed (%s) — using templates.", exc)

        # Template fallback
        bank = _TEMPLATE_BANKS.get(campaign_type, _TEMPLATE_BANKS["growth_capital"])
        all_descriptions = bank["descriptions"].copy()
        random.shuffle(all_descriptions)
        return [d for d in all_descriptions if self.validate_compliance(d).passed][:count]

    # ------------------------------------------------------------------
    # Internal generation paths
    # ------------------------------------------------------------------

    def _generate_via_gemini(
        self,
        campaign_type: str,
        tone: str,
        num_variations: int,
    ) -> list[AdCopyVariation]:
        """Call the Gemini API to generate copy."""
        tone_desc = _TONE_DESCRIPTORS.get(tone, tone)
        bank = _TEMPLATE_BANKS.get(campaign_type, _TEMPLATE_BANKS["growth_capital"])
        sample_headlines = bank["headlines"][:3]
        sample_descriptions = bank["descriptions"][:3]
        random_cta = random.choice(_COMPLIANT_CTAS)

        prompt = (
            "You are an expert financial services copywriter for SunBiz Funding.\n\n"
            f"Generate {num_variations} ad copy variations for a "
            f"{campaign_type.replace('_', ' ')} campaign.\n"
            f"Tone: {tone_desc}.\n\n"
            "COMPLIANCE RULES (non-negotiable — violating these is unacceptable):\n"
            "- NEVER use: loan, MCA, merchant cash advance, guaranteed approval, "
            "hard credit pull, guarantee, guaranteed\n"
            "- USE INSTEAD: funding, advance, capital, working capital, private lending\n"
            f"- CTAs must be one of: {', '.join(_COMPLIANT_CTAS)}\n"
            "- Specific dollar amounts must be preceded by 'up to'\n"
            "- Never promise guaranteed approval or specific approval timelines\n"
            "- Company name: SunBiz Funding\n\n"
            "STYLE REFERENCE (do not copy directly — use as inspiration):\n"
            f"Sample headlines: {sample_headlines}\n"
            f"Sample descriptions: {sample_descriptions}\n\n"
            f"Return ONLY a JSON array of {num_variations} objects. "
            "Each object must have exactly these keys:\n"
            "  headline    — short (max 40 chars), punchy\n"
            "  description — 1-2 sentences (max 125 chars), ends with a CTA\n"
            "  message     — longer post text (2-3 sentences) for Facebook feed\n"
            f"  cta         — one of: {', '.join(_COMPLIANT_CTAS)}\n\n"
            "No markdown, no explanation — pure JSON array only."
        )

        return self._call_gemini_and_parse(prompt, campaign_type, tone, fallback_count=num_variations)

    def _call_gemini_and_parse(
        self,
        prompt: str,
        campaign_type: str,
        tone: str,
        fallback_count: int = 3,
    ) -> list[AdCopyVariation]:
        """
        Call Gemini, parse the JSON response, validate compliance, and
        fall back to templates on any failure.
        """
        try:
            raw = self._call_llm_raw(prompt)
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("Gemini response is not a JSON array.")

            variations: list[AdCopyVariation] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                headline = str(item.get("headline", ""))
                description = str(item.get("description", ""))
                message = str(item.get("message", ""))
                cta = str(item.get("cta", random.choice(_COMPLIANT_CTAS)))

                # Enforce compliance — skip violating items
                combined = f"{headline} {description} {message}"
                result = self.validate_compliance(combined)
                if not result.passed:
                    log.warning(
                        "Gemini produced non-compliant copy (skipping): %s",
                        result.violations,
                    )
                    continue

                variations.append(
                    AdCopyVariation(
                        headline=headline,
                        description=description,
                        message=message,
                        cta=cta,
                        campaign_type=campaign_type,
                        tone=tone,
                        source=self._last_provider,
                    )
                )

            if variations:
                return variations

            log.warning("All Gemini variations failed compliance — falling back to templates.")

        except Exception as exc:  # pylint: disable=broad-except
            log.warning("Gemini call failed (%s) — falling back to templates.", exc)

        return self._generate_from_templates(campaign_type, tone, fallback_count)

    def _call_llm_raw(self, prompt: str) -> str:
        """Provider-preferring raw text call: Claude first, Gemini as fallback.

        Records the provider that produced the text on ``self._last_provider``
        so callers can tag the output's ``source`` accurately. Raises if no
        provider is configured (callers catch and fall back to templates).
        """
        if self._use_claude:
            try:
                text = self._call_claude_raw(prompt)
                self._last_provider = "claude"
                return text
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Claude call failed (%s) — trying Gemini fallback.", exc)
        if self._use_gemini:
            text = self._call_gemini_raw(prompt)
            self._last_provider = "gemini"
            return text
        raise RuntimeError("no LLM provider configured")

    def _call_claude_raw(self, prompt: str) -> str:
        """
        POST to the Anthropic Messages API and return the model's raw text,
        with any markdown JSON fences stripped (mirrors _call_gemini_raw).
        """
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._claude_model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        raw_text = "".join(
            blk.get("text", "")
            for blk in data.get("content", [])
            if blk.get("type") == "text"
        )
        if not raw_text:
            raise ValueError("Empty text in Anthropic response.")

        # Strip markdown code fences if the model wraps JSON in them
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        raw_text = re.sub(r"\s*```$", "", raw_text.strip())
        return raw_text.strip()

    def _call_gemini_raw(self, prompt: str) -> str:
        """
        Make a direct HTTP POST to the Gemini generateContent endpoint.
        Returns the raw text response from the model.
        """
        url = f"{_GEMINI_API_URL}?key={self._gemini_api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048,
            },
        }
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Navigate the Gemini response structure
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates in Gemini response.")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("No parts in Gemini response candidate.")

        raw_text: str = parts[0].get("text", "")

        # Strip markdown code fences if Gemini wraps JSON in them
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        raw_text = re.sub(r"\s*```$", "", raw_text.strip())

        return raw_text.strip()

    def _generate_from_templates(
        self,
        campaign_type: str,
        tone: str,
        num_variations: int,
    ) -> list[AdCopyVariation]:
        """
        Generate copy from the built-in template banks.
        Shuffles banks and picks unique combinations.
        """
        bank = _TEMPLATE_BANKS.get(campaign_type, _TEMPLATE_BANKS["growth_capital"])

        headlines = bank["headlines"].copy()
        descriptions = bank["descriptions"].copy()
        messages = bank.get("messages", ["Discover your business funding options with SunBiz Funding today."])

        random.shuffle(headlines)
        random.shuffle(descriptions)

        variations: list[AdCopyVariation] = []
        for i in range(min(num_variations, len(headlines))):
            headline = headlines[i % len(headlines)]
            description = descriptions[i % len(descriptions)]
            message = messages[i % len(messages)]
            cta = _COMPLIANT_CTAS[i % len(_COMPLIANT_CTAS)]

            # Apply tone micro-adjustments for template copy
            headline, description = _apply_tone(headline, description, tone)

            result = self.validate_compliance(f"{headline} {description} {message}")
            if not result.passed:
                log.warning("Template copy failed compliance (unexpected): %s", result.violations)
                continue

            variations.append(
                AdCopyVariation(
                    headline=headline,
                    description=description,
                    message=message,
                    cta=cta,
                    campaign_type=campaign_type,
                    tone=tone,
                    source="template",
                )
            )

        return variations

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_campaign_type(self, campaign_type: str) -> None:
        if campaign_type not in self._SUPPORTED_CAMPAIGN_TYPES:
            raise ValueError(
                f"Unsupported campaign type: '{campaign_type}'. "
                f"Must be one of: {sorted(self._SUPPORTED_CAMPAIGN_TYPES)}"
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_tone(headline: str, description: str, tone: str) -> tuple[str, str]:
    """
    Apply lightweight tone adjustments to template copy.
    These are cosmetic tweaks only — not deep rewrites.
    """
    if tone == "urgent":
        if not any(w in headline.lower() for w in ["today", "now", "fast", "quick", "same"]):
            headline = headline.rstrip(".") + " — Act Today"
    elif tone == "empathetic":
        if not description.startswith("We understand"):
            description = description.replace(
                "SunBiz Funding",
                "We at SunBiz Funding",
                1,
            )
    return headline, description


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    gen = AdCopyGenerator()

    print("\n" + "=" * 65)
    print("  SunBiz Funding — Ad Copy Generator Demo")
    print("=" * 65)

    campaign_types = [
        "growth_capital",
        "consolidation",
        "fast_funding",
        "industry",
        "social_proof",
    ]

    for ctype in campaign_types:
        print(f"\n{'—' * 65}")
        print(f"  Campaign Type: {ctype.replace('_', ' ').title()}")
        print(f"{'—' * 65}")

        variations = gen.generate_ad_copy(ctype, tone="confident", num_variations=2)
        for i, v in enumerate(variations, 1):
            print(f"\n  Variation {i} [{v.source}]:")
            print(f"    Headline:    {v.headline}")
            print(f"    Description: {v.description}")
            print(f"    CTA:         {v.cta}")

    # Compliance validation demo
    print("\n" + "=" * 65)
    print("  Compliance Validation Demo")
    print("=" * 65)

    test_cases = [
        ("PASS", "Get up to $500K in working capital. See if you qualify."),
        ("FAIL", "Get a business loan today — guaranteed approval, no hard credit pull."),
        ("FAIL", "MCA consolidation — best merchant cash advance rates."),
        ("PASS", "Consolidate your business advances with one simple payment. Apply now."),
    ]

    for expected, text in test_cases:
        result = gen.validate_compliance(text)
        status = "PASS" if result.passed else "FAIL"
        match = "CORRECT" if status == expected else "UNEXPECTED"
        print(f"\n  [{status}] ({match}) {text[:70]}")
        if result.violations:
            for v in result.violations:
                print(f"    Violation: {v}")
        if result.suggestions:
            for s in result.suggestions:
                print(f"    Suggestion: {s}")

    # Headline-only and description-only demo
    print("\n" + "=" * 65)
    print("  Headlines Only — Growth Capital (5 headlines)")
    print("=" * 65)
    headlines = gen.generate_headlines("growth_capital", count=5)
    for h in headlines:
        print(f"  - {h}")

    print("\n" + "=" * 65)
    print("  Descriptions Only — Consolidation (3 descriptions)")
    print("=" * 65)
    descriptions = gen.generate_descriptions("consolidation", count=3)
    for d in descriptions:
        print(f"  - {d}")

    print("\n" + "=" * 65)
