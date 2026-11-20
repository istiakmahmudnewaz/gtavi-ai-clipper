import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from scripts.common import DATA_DIR

PAYOUTS_FILE = DATA_DIR / "payouts.json"

def load_payouts_data() -> Dict[str, Any]:
    """
    Loads payouts and campaigns database.
    """
    if not PAYOUTS_FILE.exists():
        return {"campaigns": [], "default_cpm": 2.50}
    try:
        with open(PAYOUTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"campaigns": [], "default_cpm": 2.50}

def save_payouts_data(data: Dict[str, Any]):
    """
    Saves payouts data to disk.
    """
    PAYOUTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PAYOUTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def calculate_revenue(views: int, cpm: float) -> float:
    """
    Computes revenue = (views / 1000) * CPM
    """
    return round((views / 1000.0) * cpm, 2)

def add_post_campaign(
    title: str,
    platform: str,
    views: int,
    cpm: Optional[float] = None,
    url: str = "",
    date_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Adds or updates a post entry in campaigns tracker.
    """
    data = load_payouts_data()
    cpm_val = float(cpm if cpm is not None else data.get("default_cpm", 2.50))
    revenue = calculate_revenue(views, cpm_val)
    date_val = date_str or datetime.now().strftime("%Y-%m-%d")

    campaign_id = f"camp_{len(data['campaigns']) + 1}_{int(datetime.now().timestamp()) % 10000}"

    new_entry = {
        "id": campaign_id,
        "title": title.strip(),
        "platform": platform.strip(),
        "views": int(views),
        "cpm": round(cpm_val, 2),
        "revenue": revenue,
        "url": url.strip(),
        "date": date_val,
        "status": "Active"
    }

    data["campaigns"].insert(0, new_entry)
    save_payouts_data(data)
    return new_entry

def get_payouts_summary() -> Dict[str, Any]:
    """
    Computes high-level analytics: total views, total revenue, average CPM, and platform breakdown.
    """
    data = load_payouts_data()
    campaigns = data.get("campaigns", [])

    total_views = sum(c.get("views", 0) for c in campaigns)
    total_rev = sum(c.get("revenue", 0.0) for c in campaigns)
    avg_cpm = round(total_rev / (total_views / 1000.0), 2) if total_views > 0 else 2.50

    platforms = {}
    for c in campaigns:
        p = c.get("platform", "Other")
        if p not in platforms:
            platforms[p] = {"views": 0, "revenue": 0.0, "count": 0}
        platforms[p]["views"] += c.get("views", 0)
        platforms[p]["revenue"] += c.get("revenue", 0.0)
        platforms[p]["count"] += 1

    return {
        "total_campaigns": len(campaigns),
        "total_views": total_views,
        "total_revenue": round(total_rev, 2),
        "average_cpm": avg_cpm,
        "platform_breakdown": platforms,
        "campaigns": campaigns
    }

def main():
    parser = argparse.ArgumentParser(description="Short-Form Video Payouts & Revenue Tracker")
    parser.add_argument("--add", action="store_true", help="Add new post")
    parser.add_argument("--title", help="Post title")
    parser.add_argument("--platform", default="TikTok", help="Platform (TikTok, Shorts, Reels)")
    parser.add_argument("--views", type=int, default=0, help="Views count")
    parser.add_argument("--cpm", type=float, default=2.50, help="CPM in dollars")
    parser.add_argument("--url", default="", help="Post URL")
    args = parser.parse_args()

    if args.add and args.title:
        entry = add_post_campaign(args.title, args.platform, args.views, args.cpm, args.url)
        print(f"Added campaign: {entry['title']} -> ${entry['revenue']:,.2f}")
    else:
        summary = get_payouts_summary()
        print("\n=== Short-Form Earnings & Performance Summary ===")
        print(f"Total Posts:    {summary['total_campaigns']}")
        print(f"Total Views:    {summary['total_views']:,}")
        print(f"Total Revenue:  ${summary['total_revenue']:,.2f}")
        print(f"Average CPM:    ${summary['average_cpm']:.2f}")

if __name__ == "__main__":
    main()
