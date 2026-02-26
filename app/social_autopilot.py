"""
PrimeHaul Leads — Social Media Auto-Pilot.

Generates branded social media content via OpenAI, creates images with Pillow,
publishes to Facebook, Instagram, X (Twitter), and LinkedIn on a schedule,
and tracks engagement metrics.
"""

import io
import json
import logging
import random
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import tweepy
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import SocialAccount, SocialConfig, SocialPost

logger = logging.getLogger("primehaul.social")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BRAND_BG = (11, 11, 12)           # #0b0b0c
BRAND_ACCENT = (46, 229, 157)     # #2ee59d
BRAND_WHITE = (255, 255, 255)
BRAND_MUTED = (160, 160, 170)
IMAGE_SIZE = (1080, 1080)

B2C_CONTENT_PILLARS = {
    "tip": {
        "label": "Moving Tips",
        "prompts": [
            "a practical moving tip that saves time or money",
            "a packing hack for household items",
            "a checklist item people forget when moving",
        ],
    },
    "stat": {
        "label": "Cost Insights",
        "prompts": [
            "a UK removal cost statistic or average price range",
            "a surprising stat about moving in the UK",
            "a money-saving fact about planning your move early",
        ],
    },
    "promo": {
        "label": "Promo",
        "prompts": [
            "why getting a free AI moving quote saves time",
            "how PrimeHaul's instant estimate helps movers plan budgets",
            "the benefit of comparing removal quotes before booking",
        ],
    },
    "seasonal": {
        "label": "Seasonal",
        "prompts": [
            "seasonal moving advice for the current time of year in the UK",
            "how weather or time of year affects removal costs",
            "peak vs off-peak moving seasons in the UK",
        ],
    },
    "relatable": {
        "label": "Relatable",
        "prompts": [
            "a funny, relatable observation about moving house",
            "a lighthearted moving meme-style observation",
            "a 'you know you're moving when...' style joke",
        ],
    },
}

PLATFORM_SPECS = {
    "facebook": {"max_chars": 2000, "hashtag_count": 5, "tone": "conversational and warm"},
    "instagram": {"max_chars": 2200, "hashtag_count": 15, "tone": "visual and engaging with emojis"},
    "x": {"max_chars": 275, "hashtag_count": 3, "tone": "punchy and concise"},
    "linkedin": {"max_chars": 1300, "hashtag_count": 5, "tone": "professional yet approachable"},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config(db: Session) -> SocialConfig:
    """Get or create the singleton social config row."""
    config = db.query(SocialConfig).first()
    if not config:
        config = SocialConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _pick_content_type(config: SocialConfig) -> str:
    """Weighted random selection of content type based on config mix."""
    mix = config.content_mix or {"tip": 30, "stat": 25, "promo": 25, "seasonal": 10, "relatable": 10}
    types = list(mix.keys())
    weights = [mix[t] for t in types]
    return random.choices(types, weights=weights, k=1)[0]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load a clean sans-serif font, fall back to default."""
    font_candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _get_bold_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load a bold sans-serif font."""
    font_candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return _get_font(size)


# ---------------------------------------------------------------------------
# Content Generation (OpenAI)
# ---------------------------------------------------------------------------

def generate_post_content(
    content_type: str,
    platform: str,
    config: Optional[SocialConfig] = None,
) -> Dict[str, str]:
    """
    Use OpenAI to generate a social media post.

    Returns: {"caption": "...", "hashtags": "...", "headline": "..."}
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping content generation")
        return {"caption": "", "hashtags": "", "headline": ""}

    pillar = B2C_CONTENT_PILLARS.get(content_type, B2C_CONTENT_PILLARS["tip"])
    topic_prompt = random.choice(pillar["prompts"])
    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["facebook"])
    tone = config.tone if config and config.tone else "friendly_professional"

    system_msg = (
        "You are a social media copywriter for PrimeHaul, a UK-based service that gives "
        "people free AI-powered moving estimates. Our brand voice is helpful, modern, and "
        f"slightly witty. The tone should be: {tone.replace('_', ' ')}."
    )

    user_msg = (
        f"Write a {platform} post about {topic_prompt}.\n\n"
        f"Requirements:\n"
        f"- Max {spec['max_chars']} characters for the caption\n"
        f"- Include {spec['hashtag_count']} relevant hashtags\n"
        f"- Tone: {spec['tone']}\n"
        f"- Include a subtle CTA mentioning free AI moving quotes from PrimeHaul\n"
        f"- UK English spelling\n\n"
        f"Respond in JSON format:\n"
        f'{{"caption": "...", "hashtags": "#tag1 #tag2 ...", "headline": "short 5-8 word headline for the image card"}}'
    )

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.85,
            max_tokens=500,
        )
        data = json.loads(resp.choices[0].message.content)
        return {
            "caption": data.get("caption", ""),
            "hashtags": data.get("hashtags", ""),
            "headline": data.get("headline", ""),
        }
    except Exception as e:
        logger.error(f"OpenAI content generation failed: {e}")
        return {"caption": "", "hashtags": "", "headline": ""}


# ---------------------------------------------------------------------------
# Image Generation (Pillow)
# ---------------------------------------------------------------------------

def generate_social_image(
    content_type: str,
    headline: str,
    sub_text: str = "",
) -> Optional[str]:
    """
    Generate a 1080x1080 branded social media image.

    Returns the file path to the saved image, or None on failure.
    """
    try:
        img = Image.new("RGB", IMAGE_SIZE, BRAND_BG)
        draw = ImageDraw.Draw(img)

        # Decorative accent bar at top
        draw.rectangle([(0, 0), (1080, 6)], fill=BRAND_ACCENT)

        # Accent circle decoration (top right)
        draw.ellipse([(820, -60), (1140, 260)], fill=(*BRAND_ACCENT, 30), outline=None)

        # Brand name
        brand_font = _get_bold_font(28)
        draw.text((60, 40), "PRIMEHAUL", fill=BRAND_ACCENT, font=brand_font)

        # Content type pill
        pill_font = _get_font(20)
        pillar_label = B2C_CONTENT_PILLARS.get(content_type, {}).get("label", content_type.title())
        pill_w = draw.textlength(pillar_label, font=pill_font) + 32
        draw.rounded_rectangle(
            [(60, 85), (60 + pill_w, 115)],
            radius=15,
            fill=(*BRAND_ACCENT, 40),
            outline=BRAND_ACCENT,
        )
        draw.text((76, 88), pillar_label, fill=BRAND_ACCENT, font=pill_font)

        # Main headline
        headline_font = _get_bold_font(56)
        wrapped = textwrap.fill(headline, width=22)
        y_start = 200
        for i, line in enumerate(wrapped.split("\n")):
            draw.text((60, y_start + i * 70), line, fill=BRAND_WHITE, font=headline_font)

        # Sub text
        if sub_text:
            sub_font = _get_font(30)
            sub_wrapped = textwrap.fill(sub_text, width=40)
            sub_y = y_start + (len(wrapped.split("\n")) * 70) + 40
            for i, line in enumerate(sub_wrapped.split("\n")):
                draw.text((60, sub_y + i * 40), line, fill=BRAND_MUTED, font=sub_font)

        # Bottom CTA bar
        draw.rectangle([(0, 980), (1080, 1080)], fill=(20, 20, 22))
        cta_font = _get_bold_font(24)
        draw.text((60, 1010), "Get your free AI moving quote", fill=BRAND_ACCENT, font=cta_font)
        url_font = _get_font(22)
        draw.text((60, 1042), "primehaul.co.uk", fill=BRAND_MUTED, font=url_font)

        # Accent line above CTA
        draw.rectangle([(60, 970), (300, 974)], fill=BRAND_ACCENT)

        # Save
        img_dir = Path("app/static/social")
        img_dir.mkdir(parents=True, exist_ok=True)
        filename = f"post_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{random.randint(1000,9999)}.png"
        filepath = img_dir / filename
        img.save(str(filepath), "PNG", optimize=True)
        logger.info(f"Generated social image: {filepath}")
        return str(filepath)

    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Platform Publishing
# ---------------------------------------------------------------------------

def post_to_facebook(caption: str, image_path: Optional[str] = None) -> Optional[str]:
    """Publish to Facebook Page via Graph API. Returns post ID or None."""
    token = settings.META_PAGE_ACCESS_TOKEN
    page_id = settings.META_PAGE_ID
    if not token or not page_id:
        logger.warning("Facebook credentials not configured — skipping")
        return None

    try:
        if image_path and Path(image_path).exists():
            url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
            with open(image_path, "rb") as img_file:
                resp = httpx.post(
                    url,
                    data={"message": caption, "access_token": token},
                    files={"source": img_file},
                    timeout=60,
                )
        else:
            url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
            resp = httpx.post(
                url,
                data={"message": caption, "access_token": token},
                timeout=30,
            )

        resp.raise_for_status()
        post_id = resp.json().get("id") or resp.json().get("post_id")
        logger.info(f"Posted to Facebook: {post_id}")
        return post_id

    except Exception as e:
        logger.error(f"Facebook posting failed: {e}")
        return None


def post_to_instagram(caption: str, image_path: Optional[str] = None) -> Optional[str]:
    """Publish to Instagram via Meta Graph API. Image is required."""
    token = settings.META_PAGE_ACCESS_TOKEN
    ig_account_id = settings.META_INSTAGRAM_ACCOUNT_ID
    if not token or not ig_account_id:
        logger.warning("Instagram credentials not configured — skipping")
        return None

    if not image_path or not Path(image_path).exists():
        logger.warning("Instagram requires an image — skipping")
        return None

    try:
        # Instagram requires a publicly accessible image URL.
        # For now, we upload via the container creation flow.
        # In production, the image should be hosted (e.g. on S3/CDN).
        app_url = settings.APP_URL.rstrip("/")
        # Convert local path to a URL path
        rel_path = image_path.replace("\\", "/")
        if rel_path.startswith("app/"):
            rel_path = rel_path[4:]
        image_url = f"{app_url}/{rel_path}"

        # Step 1: Create media container
        create_url = f"https://graph.facebook.com/v19.0/{ig_account_id}/media"
        create_resp = httpx.post(
            create_url,
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": token,
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        container_id = create_resp.json()["id"]

        # Step 2: Publish the container
        publish_url = f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish"
        publish_resp = httpx.post(
            publish_url,
            data={
                "creation_id": container_id,
                "access_token": token,
            },
            timeout=30,
        )
        publish_resp.raise_for_status()
        post_id = publish_resp.json().get("id")
        logger.info(f"Posted to Instagram: {post_id}")
        return post_id

    except Exception as e:
        logger.error(f"Instagram posting failed: {e}")
        return None


def post_to_x(caption: str, image_path: Optional[str] = None) -> Optional[str]:
    """Publish to X (Twitter) via Tweepy. Returns tweet ID or None."""
    api_key = settings.X_API_KEY
    api_secret = settings.X_API_SECRET
    access_token = settings.X_ACCESS_TOKEN
    access_secret = settings.X_ACCESS_TOKEN_SECRET
    if not all([api_key, api_secret, access_token, access_secret]):
        logger.warning("X/Twitter credentials not configured — skipping")
        return None

    try:
        # V1.1 auth for media upload
        auth = tweepy.OAuthHandler(api_key, api_secret)
        auth.set_access_token(access_token, access_secret)
        api_v1 = tweepy.API(auth)

        # V2 client for tweeting
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )

        media_ids = []
        if image_path and Path(image_path).exists():
            media = api_v1.media_upload(image_path)
            media_ids = [media.media_id]

        resp = client.create_tweet(
            text=caption,
            media_ids=media_ids if media_ids else None,
        )
        tweet_id = str(resp.data["id"])
        logger.info(f"Posted to X: {tweet_id}")
        return tweet_id

    except Exception as e:
        logger.error(f"X posting failed: {e}")
        return None


def post_to_linkedin(caption: str, image_path: Optional[str] = None) -> Optional[str]:
    """Publish to LinkedIn Organization via API. Returns post URN or None."""
    token = settings.LINKEDIN_ACCESS_TOKEN
    org_id = settings.LINKEDIN_ORG_ID
    if not token or not org_id:
        logger.warning("LinkedIn credentials not configured — skipping")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        image_urn = None
        if image_path and Path(image_path).exists():
            # Step 1: Register image upload
            register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
            register_body = {
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": f"urn:li:organization:{org_id}",
                    "serviceRelationships": [
                        {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                    ],
                }
            }
            reg_resp = httpx.post(register_url, headers=headers, json=register_body, timeout=30)
            reg_resp.raise_for_status()
            upload_url = reg_resp.json()["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            image_urn = reg_resp.json()["value"]["asset"]

            # Step 2: Upload the image binary
            with open(image_path, "rb") as img_file:
                upload_resp = httpx.put(
                    upload_url,
                    headers={"Authorization": f"Bearer {token}"},
                    content=img_file.read(),
                    timeout=60,
                )
                upload_resp.raise_for_status()

        # Step 3: Create the share post
        share_url = "https://api.linkedin.com/v2/ugcPosts"
        share_body: Dict[str, Any] = {
            "author": f"urn:li:organization:{org_id}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": caption},
                    "shareMediaCategory": "IMAGE" if image_urn else "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        if image_urn:
            share_body["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                {
                    "status": "READY",
                    "media": image_urn,
                }
            ]

        share_resp = httpx.post(share_url, headers=headers, json=share_body, timeout=30)
        share_resp.raise_for_status()
        post_urn = share_resp.headers.get("x-restli-id", share_resp.json().get("id"))
        logger.info(f"Posted to LinkedIn: {post_urn}")
        return post_urn

    except Exception as e:
        logger.error(f"LinkedIn posting failed: {e}")
        return None


PLATFORM_PUBLISHERS = {
    "facebook": post_to_facebook,
    "instagram": post_to_instagram,
    "x": post_to_x,
    "linkedin": post_to_linkedin,
}


# ---------------------------------------------------------------------------
# Engagement Tracking
# ---------------------------------------------------------------------------

def check_facebook_engagement(post_id: str) -> Optional[Dict]:
    """Fetch engagement metrics for a Facebook post."""
    token = settings.META_PAGE_ACCESS_TOKEN
    if not token or not post_id:
        return None
    try:
        url = f"https://graph.facebook.com/v19.0/{post_id}"
        resp = httpx.get(
            url,
            params={
                "fields": "likes.summary(true),comments.summary(true),shares",
                "access_token": token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "likes": data.get("likes", {}).get("summary", {}).get("total_count", 0),
            "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
            "shares": data.get("shares", {}).get("count", 0),
        }
    except Exception as e:
        logger.error(f"Facebook engagement check failed: {e}")
        return None


def check_x_engagement(tweet_id: str) -> Optional[Dict]:
    """Fetch engagement metrics for a tweet."""
    api_key = settings.X_API_KEY
    api_secret = settings.X_API_SECRET
    access_token = settings.X_ACCESS_TOKEN
    access_secret = settings.X_ACCESS_TOKEN_SECRET
    if not all([api_key, api_secret, access_token, access_secret]) or not tweet_id:
        return None
    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        resp = client.get_tweet(tweet_id, tweet_fields=["public_metrics"])
        metrics = resp.data.public_metrics if resp.data else {}
        return {
            "likes": metrics.get("like_count", 0),
            "comments": metrics.get("reply_count", 0),
            "shares": metrics.get("retweet_count", 0),
            "impressions": metrics.get("impression_count", 0),
        }
    except Exception as e:
        logger.error(f"X engagement check failed: {e}")
        return None


ENGAGEMENT_CHECKERS = {
    "facebook": check_facebook_engagement,
    "x": check_x_engagement,
}


# ---------------------------------------------------------------------------
# Scheduled Jobs
# ---------------------------------------------------------------------------

def generate_weekly_content():
    """Generate a week's worth of social media posts (2/day × 7 days = 14 posts)."""
    logger.info("Starting weekly content generation...")
    db = SessionLocal()
    try:
        config = _get_config(db)
        posts_per_day = config.posts_per_day or 2
        posting_times = config.posting_times or ["09:00", "18:00"]
        active_platforms = config.active_platforms or ["facebook", "instagram", "x", "linkedin"]

        now = datetime.now(timezone.utc)
        posts_created = 0

        for day_offset in range(7):
            day = now + timedelta(days=day_offset + 1)  # Start from tomorrow
            for slot_idx in range(min(posts_per_day, len(posting_times))):
                time_str = posting_times[slot_idx]
                hour, minute = int(time_str.split(":")[0]), int(time_str.split(":")[1])
                scheduled = day.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # Pick a content type
                content_type = _pick_content_type(config)

                # Generate for each active platform
                for platform in active_platforms:
                    # Check we don't already have a post scheduled for this slot
                    existing = (
                        db.query(SocialPost)
                        .filter(
                            SocialPost.platform == platform,
                            SocialPost.scheduled_for == scheduled,
                            SocialPost.status.in_(["scheduled", "published"]),
                        )
                        .first()
                    )
                    if existing:
                        continue

                    # Generate content
                    content = generate_post_content(content_type, platform, config)
                    if not content["caption"]:
                        continue

                    # Generate image
                    image_path = generate_social_image(
                        content_type,
                        content["headline"],
                        content["caption"][:80] + "..." if len(content["caption"]) > 80 else content["caption"],
                    )

                    # Combine caption + hashtags
                    full_caption = content["caption"]
                    if content["hashtags"]:
                        full_caption += "\n\n" + content["hashtags"]

                    post = SocialPost(
                        platform=platform,
                        content_type=content_type,
                        content_pillar=B2C_CONTENT_PILLARS.get(content_type, {}).get("label", content_type),
                        caption=full_caption,
                        hashtags=content["hashtags"],
                        image_path=image_path,
                        scheduled_for=scheduled,
                        status="scheduled" if config.auto_publish else "draft",
                    )
                    db.add(post)
                    posts_created += 1

        config.last_generation_at = now
        db.commit()
        logger.info(f"Weekly content generation complete: {posts_created} posts created")

    except Exception as e:
        db.rollback()
        logger.error(f"Weekly content generation failed: {e}")
    finally:
        db.close()


def publish_due_posts():
    """Check for scheduled posts that are due and publish them."""
    logger.info("Checking for due posts...")
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_posts = (
            db.query(SocialPost)
            .filter(
                SocialPost.status == "scheduled",
                SocialPost.scheduled_for <= now,
            )
            .order_by(SocialPost.scheduled_for)
            .limit(10)
            .all()
        )

        if not due_posts:
            logger.debug("No posts due for publishing")
            return

        for post in due_posts:
            publisher = PLATFORM_PUBLISHERS.get(post.platform)
            if not publisher:
                post.status = "failed"
                post.error_message = f"Unknown platform: {post.platform}"
                continue

            logger.info(f"Publishing {post.platform} post {post.id}...")
            platform_id = publisher(post.caption, post.image_path)

            if platform_id:
                post.status = "published"
                post.published_at = now
                post.platform_post_id = platform_id
                logger.info(f"Successfully published: {post.platform} -> {platform_id}")
            else:
                post.status = "failed"
                post.error_message = "Publishing returned no post ID — check platform credentials"
                logger.warning(f"Failed to publish {post.platform} post {post.id}")

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Publish due posts failed: {e}")
    finally:
        db.close()


def check_all_engagement():
    """Fetch engagement metrics for published posts from the last 7 days."""
    logger.info("Checking engagement for recent posts...")
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_posts = (
            db.query(SocialPost)
            .filter(
                SocialPost.status == "published",
                SocialPost.published_at >= cutoff,
                SocialPost.platform_post_id.isnot(None),
            )
            .all()
        )

        updated = 0
        for post in recent_posts:
            checker = ENGAGEMENT_CHECKERS.get(post.platform)
            if not checker:
                continue

            metrics = checker(post.platform_post_id)
            if metrics:
                post.engagement = metrics
                updated += 1

        db.commit()
        logger.info(f"Engagement check complete: {updated}/{len(recent_posts)} posts updated")

    except Exception as e:
        db.rollback()
        logger.error(f"Engagement check failed: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Manual actions (called from admin routes)
# ---------------------------------------------------------------------------

def force_generate_batch(db: Session) -> int:
    """Force-generate a new batch of content. Returns count of posts created."""
    generate_weekly_content()
    return (
        db.query(SocialPost)
        .filter(SocialPost.status.in_(["scheduled", "draft"]))
        .count()
    )


def manually_publish_post(db: Session, post_id: str) -> Tuple[bool, str]:
    """Manually publish a specific post. Returns (success, message)."""
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        return False, "Post not found"

    if post.status == "published":
        return False, "Post is already published"

    publisher = PLATFORM_PUBLISHERS.get(post.platform)
    if not publisher:
        return False, f"Unknown platform: {post.platform}"

    platform_id = publisher(post.caption, post.image_path)
    if platform_id:
        post.status = "published"
        post.published_at = datetime.now(timezone.utc)
        post.platform_post_id = platform_id
        db.commit()
        return True, f"Published successfully: {platform_id}"
    else:
        post.status = "failed"
        post.error_message = "Manual publish failed — check platform credentials"
        db.commit()
        return False, "Publishing failed — check platform credentials and logs"


def skip_post(db: Session, post_id: str) -> Tuple[bool, str]:
    """Skip a scheduled post. Returns (success, message)."""
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        return False, "Post not found"

    post.status = "draft"
    db.commit()
    return True, "Post moved to drafts"
