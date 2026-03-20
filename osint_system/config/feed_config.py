"""Tiered RSS feed configuration for OSINT news ingestion.

Adapted from the geopol project's production feed infrastructure.
90+ feeds across wire services, major outlets, think tanks, regional sources,
defense/OSINT specialists, and crisis monitors.

Tier system:
  TIER_1 -- Wire services, major outlets, government/IO sources
  TIER_2 -- Regional outlets, think tanks, specialty analysis
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal


class FeedTier(IntEnum):
    """Polling frequency tier. Lower = more authoritative."""

    TIER_1 = 1
    TIER_2 = 2


FeedCategory = Literal[
    "wire",
    "mainstream",
    "government",
    "intl_org",
    "defense",
    "intel",
    "thinktank",
    "crisis",
    "regional",
    "finance",
    "energy",
]


@dataclass(frozen=True, slots=True)
class FeedSource:
    """Immutable RSS feed definition."""

    name: str
    url: str
    tier: FeedTier
    category: FeedCategory
    lang: str = "en"


# ---------------------------------------------------------------------------
# TIER 1: Wire services, major global outlets, government & IO sources
# ---------------------------------------------------------------------------

TIER_1_FEEDS: list[FeedSource] = [
    # --- Wire services ---
    FeedSource("Reuters World", "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("Reuters Business", "https://news.google.com/rss/search?q=site:reuters.com+business+markets&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("AP News", "https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("AFP", "https://news.google.com/rss/search?q=AFP+agence+france+presse&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("Bloomberg", "https://news.google.com/rss/search?q=site:bloomberg.com+when:1d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("Xinhua", "https://news.google.com/rss/search?q=site:xinhuanet.com+OR+Xinhua+when:1d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),
    FeedSource("TASS", "https://news.google.com/rss/search?q=site:tass.com+OR+TASS+Russia+when:1d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "wire"),

    # --- Major global outlets ---
    FeedSource("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", FeedTier.TIER_1, "mainstream"),
    FeedSource("Guardian World", "https://www.theguardian.com/world/rss", FeedTier.TIER_1, "mainstream"),
    FeedSource("CNN World", "http://rss.cnn.com/rss/cnn_world.rss", FeedTier.TIER_1, "mainstream"),
    FeedSource("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", FeedTier.TIER_1, "mainstream"),
    FeedSource("NPR News", "https://feeds.npr.org/1001/rss.xml", FeedTier.TIER_1, "mainstream"),
    FeedSource("France 24", "https://www.france24.com/en/rss", FeedTier.TIER_1, "mainstream"),
    FeedSource("DW News", "https://rss.dw.com/xml/rss-en-all", FeedTier.TIER_1, "mainstream"),
    FeedSource("Financial Times", "https://www.ft.com/rss/home", FeedTier.TIER_1, "finance"),
    FeedSource("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", FeedTier.TIER_1, "finance"),

    # --- Government & International Organizations ---
    FeedSource("White House", "https://news.google.com/rss/search?q=site:whitehouse.gov&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "government"),
    FeedSource("State Dept", "https://news.google.com/rss/search?q=site:state.gov+OR+%22State+Department%22&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "government"),
    FeedSource("Pentagon", "https://news.google.com/rss/search?q=site:defense.gov+OR+Pentagon&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_1, "government"),
    FeedSource("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml", FeedTier.TIER_1, "intl_org"),

    # --- Tier-1 defense ---
    FeedSource("UK MOD", "https://www.gov.uk/government/organisations/ministry-of-defence.atom", FeedTier.TIER_1, "defense"),
]

# ---------------------------------------------------------------------------
# TIER 2: Regional outlets, think tanks, specialty analysis
# ---------------------------------------------------------------------------

TIER_2_FEEDS: list[FeedSource] = [
    # --- Think tanks & analysis ---
    FeedSource("Foreign Policy", "https://foreignpolicy.com/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("Foreign Affairs", "https://www.foreignaffairs.com/rss.xml", FeedTier.TIER_2, "thinktank"),
    FeedSource("Atlantic Council", "https://www.atlanticcouncil.org/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("CSIS", "https://news.google.com/rss/search?q=site:csis.org+when:7d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "thinktank"),
    FeedSource("RAND", "https://www.rand.org/rss/all.xml", FeedTier.TIER_2, "thinktank"),
    FeedSource("Brookings", "https://www.brookings.edu/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("Carnegie", "https://carnegieendowment.org/rss/", FeedTier.TIER_2, "thinktank"),
    FeedSource("War on the Rocks", "https://warontherocks.com/feed", FeedTier.TIER_2, "thinktank"),
    FeedSource("AEI", "https://www.aei.org/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("Responsible Statecraft", "https://responsiblestatecraft.org/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("RUSI", "https://news.google.com/rss/search?q=site:rusi.org+when:3d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "thinktank"),
    FeedSource("Jamestown", "https://jamestown.org/feed/", FeedTier.TIER_2, "thinktank"),
    FeedSource("Chatham House", "https://news.google.com/rss/search?q=site:chathamhouse.org+when:7d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "thinktank"),

    # --- Defense & OSINT ---
    FeedSource("Defense One", "https://www.defenseone.com/rss/all/", FeedTier.TIER_2, "defense"),
    FeedSource("Breaking Defense", "https://breakingdefense.com/feed/", FeedTier.TIER_2, "defense"),
    FeedSource("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", FeedTier.TIER_2, "defense"),
    FeedSource("USNI News", "https://news.usni.org/feed", FeedTier.TIER_2, "defense"),
    FeedSource("Bellingcat", "https://www.bellingcat.com/feed/", FeedTier.TIER_2, "intel"),

    # --- Crisis monitoring ---
    FeedSource("CrisisWatch", "https://www.crisisgroup.org/rss", FeedTier.TIER_2, "crisis"),

    # --- Regional: Asia-Pacific ---
    FeedSource("BBC Asia", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", FeedTier.TIER_2, "regional"),
    FeedSource("The Diplomat", "https://thediplomat.com/feed/", FeedTier.TIER_2, "regional"),
    FeedSource("South China Morning Post", "https://www.scmp.com/rss/91/feed/", FeedTier.TIER_2, "regional"),
    FeedSource("Nikkei Asia", "https://news.google.com/rss/search?q=site:asia.nikkei.com+when:3d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "regional"),

    # --- Energy & commodities ---
    FeedSource("Mining & Resources", "https://news.google.com/rss/search?q=(lithium+OR+%22rare+earth%22+OR+cobalt+OR+mining)+when:3d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "energy"),

    # --- Finance (geopolitical-adjacent) ---
    FeedSource("MarketWatch", "https://news.google.com/rss/search?q=site:marketwatch.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en", FeedTier.TIER_2, "finance"),
]


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

ALL_FEEDS: list[FeedSource] = TIER_1_FEEDS + TIER_2_FEEDS

PROPAGANDA_RISK: dict[str, dict[str, str]] = {
    "Xinhua": {"risk": "high", "state": "China", "note": "Official CCP news agency"},
    "TASS": {"risk": "high", "state": "Russia", "note": "Russian state news agency"},
    "Al Jazeera": {"risk": "medium", "state": "Qatar", "note": "Qatari state-funded"},
    "France 24": {"risk": "medium", "state": "France", "note": "French state-funded"},
    "DW News": {"risk": "medium", "state": "Germany", "note": "German state-funded"},
}


def get_propaganda_risk(source_name: str) -> str:
    """Return 'low', 'medium', or 'high' propaganda risk for a source."""
    profile = PROPAGANDA_RISK.get(source_name)
    return profile["risk"] if profile else "low"
