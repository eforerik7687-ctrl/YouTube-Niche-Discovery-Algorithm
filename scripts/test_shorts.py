"""Find SpraySword Shorts and calculate time-window views."""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tubescrape import YouTube
from src.analysis.propagator import KeywordPropagator


def safe(s):
    if not s:
        return ""
    return re.sub(r'[^\x20-\x7e　-ヿ一-鿿]', '?', str(s))


def main():
    with YouTube() as yt:
        # 1. Find SpraySword channel
        cid = yt.extract_channel_id("@spraysword")
        print(f"SpraySword channel ID: {cid}")

        # 2. Get channel Shorts (this endpoint has accurate Shorts data)
        print(f"\n=== get_channel_shorts() ===")
        shorts_result = yt.get_channel_shorts(cid)
        print(f"  Shorts found: {len(shorts_result.shorts)}")

        total_shorts_views = 0
        for s in shorts_result.shorts[:10]:
            views = KeywordPropagator._parse_view_count(s.view_count)
            total_shorts_views += views
            print(f"  {safe(s.view_count or '?'):>12}  {safe(s.title)[:55]}")
        print(f"  ...")
        print(f"  Total Shorts views (discovered): {total_shorts_views:,}")

        # Note: ShortResult has no published_text, so we can't do 7d/30d from this endpoint
        # But we CAN search for the channel's videos by upload_date

        # 3. Search for channel's recent videos
        print(f"\n=== Search for 'spraysword' (recent) ===")
        r = yt.search("spraysword", max_results=50, sort_by="upload_date", type="video")

        total_views = 0
        views_7d = 0
        views_30d = 0
        shorts_found = 0
        for v in r.videos:
            parsed = KeywordPropagator._parse_view_count(v.view_count)
            total_views += parsed
            if v.is_short or '/shorts/' in (v.url or ''):
                shorts_found += 1
            d = KeywordPropagator._days_from_published(v.published_text)
            if d is not None:
                if d <= 30:
                    views_30d += parsed
                    if d <= 7:
                        views_7d += parsed

        print(f"  Videos: {len(r.videos)}")
        print(f"  Shorts detected: {shorts_found}")
        print(f"  Total views: {total_views:,}")
        print(f"  Views 7d: {views_7d:,}")
        print(f"  Views 30d: {views_30d:,}")

        for v in r.videos[:5]:
            d = KeywordPropagator._days_from_published(v.published_text)
            parsed = KeywordPropagator._parse_view_count(v.view_count)
            is_s = 'S' if v.is_short else ' '
            url_s = '/shorts' if '/shorts/' in (v.url or '') else '/watch '
            print(f"  [{is_s}|{url_s}] {str(d or '?'):>4s}d  {parsed:>10,}  {safe(v.channel):25s}  {safe(v.title)[:55]}")


if __name__ == "__main__":
    main()
