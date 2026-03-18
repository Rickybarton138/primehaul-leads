"""
PrimeHaul Leads — SEO Routes.

Programmatic geo/local landing pages, sitemap.xml, robots.txt,
and technical SEO endpoints for Google Page 1 targeting.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import settings

logger = logging.getLogger("primehaul.seo")

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# UK Cities Data — top 60+ cities for programmatic geo pages
# ---------------------------------------------------------------------------
UK_CITIES = {
    "london": {"name": "London", "county": "Greater London", "population": "9M+", "lat": 51.5074, "lng": -0.1278},
    "manchester": {"name": "Manchester", "county": "Greater Manchester", "population": "550K+", "lat": 53.4808, "lng": -2.2426},
    "birmingham": {"name": "Birmingham", "county": "West Midlands", "population": "1.1M+", "lat": 52.4862, "lng": -1.8904},
    "leeds": {"name": "Leeds", "county": "West Yorkshire", "population": "800K+", "lat": 53.8008, "lng": -1.5491},
    "glasgow": {"name": "Glasgow", "county": "Scotland", "population": "635K+", "lat": 55.8642, "lng": -4.2518},
    "liverpool": {"name": "Liverpool", "county": "Merseyside", "population": "500K+", "lat": 53.4084, "lng": -2.9916},
    "edinburgh": {"name": "Edinburgh", "county": "Scotland", "population": "525K+", "lat": 55.9533, "lng": -3.1883},
    "bristol": {"name": "Bristol", "county": "Somerset", "population": "470K+", "lat": 51.4545, "lng": -2.5879},
    "sheffield": {"name": "Sheffield", "county": "South Yorkshire", "population": "585K+", "lat": 53.3811, "lng": -1.4701},
    "newcastle": {"name": "Newcastle", "county": "Tyne and Wear", "population": "300K+", "lat": 54.9783, "lng": -1.6178},
    "nottingham": {"name": "Nottingham", "county": "Nottinghamshire", "population": "330K+", "lat": 52.9548, "lng": -1.1581},
    "cardiff": {"name": "Cardiff", "county": "Wales", "population": "365K+", "lat": 51.4816, "lng": -3.1791},
    "leicester": {"name": "Leicester", "county": "Leicestershire", "population": "370K+", "lat": 52.6369, "lng": -1.1398},
    "coventry": {"name": "Coventry", "county": "West Midlands", "population": "370K+", "lat": 52.4068, "lng": -1.5197},
    "bradford": {"name": "Bradford", "county": "West Yorkshire", "population": "540K+", "lat": 53.7960, "lng": -1.7594},
    "belfast": {"name": "Belfast", "county": "Northern Ireland", "population": "345K+", "lat": 54.5973, "lng": -5.9301},
    "stoke-on-trent": {"name": "Stoke-on-Trent", "county": "Staffordshire", "population": "260K+", "lat": 53.0027, "lng": -2.1794},
    "wolverhampton": {"name": "Wolverhampton", "county": "West Midlands", "population": "265K+", "lat": 52.5870, "lng": -2.1288},
    "plymouth": {"name": "Plymouth", "county": "Devon", "population": "265K+", "lat": 50.3755, "lng": -4.1427},
    "southampton": {"name": "Southampton", "county": "Hampshire", "population": "255K+", "lat": 50.9097, "lng": -1.4044},
    "reading": {"name": "Reading", "county": "Berkshire", "population": "230K+", "lat": 51.4543, "lng": -0.9781},
    "derby": {"name": "Derby", "county": "Derbyshire", "population": "260K+", "lat": 52.9225, "lng": -1.4746},
    "swansea": {"name": "Swansea", "county": "Wales", "population": "245K+", "lat": 51.6214, "lng": -3.9436},
    "aberdeen": {"name": "Aberdeen", "county": "Scotland", "population": "230K+", "lat": 57.1497, "lng": -2.0943},
    "oxford": {"name": "Oxford", "county": "Oxfordshire", "population": "155K+", "lat": 51.7520, "lng": -1.2577},
    "cambridge": {"name": "Cambridge", "county": "Cambridgeshire", "population": "145K+", "lat": 52.2053, "lng": 0.1218},
    "york": {"name": "York", "county": "North Yorkshire", "population": "210K+", "lat": 53.9591, "lng": -1.0815},
    "peterborough": {"name": "Peterborough", "county": "Cambridgeshire", "population": "205K+", "lat": 52.5695, "lng": -0.2405},
    "brighton": {"name": "Brighton", "county": "East Sussex", "population": "290K+", "lat": 50.8225, "lng": -0.1372},
    "norwich": {"name": "Norwich", "county": "Norfolk", "population": "215K+", "lat": 52.6309, "lng": 1.2974},
    "portsmouth": {"name": "Portsmouth", "county": "Hampshire", "population": "215K+", "lat": 50.8198, "lng": -1.0880},
    "swindon": {"name": "Swindon", "county": "Wiltshire", "population": "225K+", "lat": 51.5558, "lng": -1.7797},
    "milton-keynes": {"name": "Milton Keynes", "county": "Buckinghamshire", "population": "250K+", "lat": 52.0406, "lng": -0.7594},
    "northampton": {"name": "Northampton", "county": "Northamptonshire", "population": "225K+", "lat": 52.2405, "lng": -0.9027},
    "exeter": {"name": "Exeter", "county": "Devon", "population": "130K+", "lat": 50.7184, "lng": -3.5339},
    "bath": {"name": "Bath", "county": "Somerset", "population": "100K+", "lat": 51.3811, "lng": -2.3590},
    "cheltenham": {"name": "Cheltenham", "county": "Gloucestershire", "population": "120K+", "lat": 51.8994, "lng": -2.0783},
    "gloucester": {"name": "Gloucester", "county": "Gloucestershire", "population": "130K+", "lat": 51.8642, "lng": -2.2382},
    "ipswich": {"name": "Ipswich", "county": "Suffolk", "population": "140K+", "lat": 52.0567, "lng": 1.1482},
    "bournemouth": {"name": "Bournemouth", "county": "Dorset", "population": "195K+", "lat": 50.7192, "lng": -1.8808},
    "middlesbrough": {"name": "Middlesbrough", "county": "North Yorkshire", "population": "140K+", "lat": 54.5742, "lng": -1.2350},
    "hull": {"name": "Hull", "county": "East Yorkshire", "population": "260K+", "lat": 53.7457, "lng": -0.3367},
    "sunderland": {"name": "Sunderland", "county": "Tyne and Wear", "population": "175K+", "lat": 54.9061, "lng": -1.3831},
    "dundee": {"name": "Dundee", "county": "Scotland", "population": "150K+", "lat": 56.4620, "lng": -2.9707},
    "blackpool": {"name": "Blackpool", "county": "Lancashire", "population": "140K+", "lat": 53.8175, "lng": -3.0357},
    "luton": {"name": "Luton", "county": "Bedfordshire", "population": "225K+", "lat": 51.8787, "lng": -0.4200},
    "warrington": {"name": "Warrington", "county": "Cheshire", "population": "210K+", "lat": 53.3900, "lng": -2.5970},
    "colchester": {"name": "Colchester", "county": "Essex", "population": "190K+", "lat": 51.8891, "lng": 0.9031},
    "crawley": {"name": "Crawley", "county": "West Sussex", "population": "115K+", "lat": 51.1092, "lng": -0.1872},
    "basingstoke": {"name": "Basingstoke", "county": "Hampshire", "population": "115K+", "lat": 51.2667, "lng": -1.0873},
    "worcester": {"name": "Worcester", "county": "Worcestershire", "population": "100K+", "lat": 52.1936, "lng": -2.2216},
    "lincoln": {"name": "Lincoln", "county": "Lincolnshire", "population": "105K+", "lat": 53.2307, "lng": -0.5406},
    "chester": {"name": "Chester", "county": "Cheshire", "population": "130K+", "lat": 53.1930, "lng": -2.8931},
    "salisbury": {"name": "Salisbury", "county": "Wiltshire", "population": "45K+", "lat": 51.0688, "lng": -1.7945},
    "durham": {"name": "Durham", "county": "County Durham", "population": "50K+", "lat": 54.7753, "lng": -1.5849},
    "harrogate": {"name": "Harrogate", "county": "North Yorkshire", "population": "80K+", "lat": 53.9921, "lng": -1.5418},
    "guildford": {"name": "Guildford", "county": "Surrey", "population": "80K+", "lat": 51.2362, "lng": -0.5704},
    "maidstone": {"name": "Maidstone", "county": "Kent", "population": "175K+", "lat": 51.2724, "lng": 0.5292},
    "canterbury": {"name": "Canterbury", "county": "Kent", "population": "55K+", "lat": 51.2802, "lng": 1.0789},
    "inverness": {"name": "Inverness", "county": "Scotland", "population": "65K+", "lat": 57.4778, "lng": -4.2247},
}

# Popular removal routes for programmatic route pages
POPULAR_ROUTES = [
    ("london", "manchester"), ("london", "birmingham"), ("london", "bristol"),
    ("london", "leeds"), ("london", "edinburgh"), ("london", "glasgow"),
    ("london", "brighton"), ("london", "cambridge"), ("london", "oxford"),
    ("london", "southampton"), ("london", "reading"), ("london", "cardiff"),
    ("london", "liverpool"), ("london", "nottingham"), ("london", "sheffield"),
    ("london", "newcastle"), ("london", "exeter"), ("london", "bath"),
    ("manchester", "london"), ("manchester", "leeds"), ("manchester", "liverpool"),
    ("manchester", "birmingham"), ("manchester", "sheffield"), ("manchester", "glasgow"),
    ("manchester", "edinburgh"), ("manchester", "nottingham"), ("manchester", "bristol"),
    ("birmingham", "london"), ("birmingham", "manchester"), ("birmingham", "bristol"),
    ("birmingham", "nottingham"), ("birmingham", "leicester"), ("birmingham", "leeds"),
    ("edinburgh", "london"), ("edinburgh", "glasgow"), ("edinburgh", "manchester"),
    ("edinburgh", "aberdeen"), ("edinburgh", "dundee"),
    ("glasgow", "edinburgh"), ("glasgow", "london"), ("glasgow", "manchester"),
    ("bristol", "london"), ("bristol", "birmingham"), ("bristol", "cardiff"),
    ("bristol", "bath"), ("bristol", "exeter"),
    ("leeds", "london"), ("leeds", "manchester"), ("leeds", "sheffield"),
    ("leeds", "york"), ("leeds", "newcastle"),
    ("liverpool", "london"), ("liverpool", "manchester"), ("liverpool", "birmingham"),
    ("newcastle", "london"), ("newcastle", "edinburgh"), ("newcastle", "leeds"),
    ("cardiff", "london"), ("cardiff", "bristol"), ("cardiff", "swansea"),
    ("cambridge", "london"), ("oxford", "london"), ("brighton", "london"),
    ("nottingham", "london"), ("nottingham", "birmingham"), ("nottingham", "sheffield"),
    ("southampton", "london"), ("portsmouth", "london"), ("reading", "london"),
]


def _get_nearby_cities(slug: str, limit: int = 6) -> list:
    """Get nearby cities for internal linking mesh."""
    city = UK_CITIES.get(slug)
    if not city:
        return []

    import math

    def _dist(c1, c2):
        R = 3959
        lat1, lat2 = math.radians(c1["lat"]), math.radians(c2["lat"])
        dlat = math.radians(c2["lat"] - c1["lat"])
        dlng = math.radians(c2["lng"] - c1["lng"])
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distances = []
    for s, c in UK_CITIES.items():
        if s != slug:
            distances.append((s, c, _dist(city, c)))
    distances.sort(key=lambda x: x[2])
    return [(s, c) for s, c, _ in distances[:limit]]


def _get_routes_for_city(slug: str) -> list:
    """Get popular routes involving this city."""
    routes = []
    for from_slug, to_slug in POPULAR_ROUTES:
        if from_slug == slug or to_slug == slug:
            from_city = UK_CITIES.get(from_slug, {}).get("name", from_slug.title())
            to_city = UK_CITIES.get(to_slug, {}).get("name", to_slug.title())
            routes.append({
                "from_slug": from_slug,
                "to_slug": to_slug,
                "from_name": from_city,
                "to_name": to_city,
                "url": f"/removals/{from_slug}-to-{to_slug}",
            })
    return routes[:8]


def _estimate_route_distance(from_slug: str, to_slug: str) -> int:
    """Estimate distance between two cities in miles."""
    import math

    c1 = UK_CITIES.get(from_slug)
    c2 = UK_CITIES.get(to_slug)
    if not c1 or not c2:
        return 0

    R = 3959
    lat1, lat2 = math.radians(c1["lat"]), math.radians(c2["lat"])
    dlat = math.radians(c2["lat"] - c1["lat"])
    dlng = math.radians(c2["lng"] - c1["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(c)


# ---------------------------------------------------------------------------
# llms.txt — Machine-readable business description for AI crawlers (GEO)
# ---------------------------------------------------------------------------
@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    base_url = settings.CANONICAL_DOMAIN.rstrip("/")
    cities_sample = ", ".join(c["name"] for c in list(UK_CITIES.values())[:15])
    return f"""# PrimeHaul Leads
> Free AI-powered moving estimates for UK house movers. Consumers upload room photos, receive instant AI inventory analysis and cost estimates, then connect with verified removal companies.

## How It Works
- Consumer takes an interactive moving survey with photo uploads
- AI vision analyses room photos to extract a full inventory (items, dimensions, weight)
- System calculates an instant cost estimate based on distance, volume, and access
- Consumer submits contact details as a qualified lead
- Verified removal companies purchase pre-qualified leads via the marketplace

## Services
- AI-powered moving inventory analysis
- Instant removal cost estimates
- Lead generation for removal companies
- UK-wide coverage with local geo pages

## Coverage
- UK nationwide: {cities_sample}, and 45+ more cities
- Popular routes: London to Manchester, London to Birmingham, Edinburgh to Glasgow, and 60+ more

## Contact
- Website: {base_url}
- Start a quote: {base_url}/start

## Key Facts
- Free for consumers — no obligation
- AI vision extracts item-level inventory from photos
- Covers house moves, flat moves, office relocations
- Distance-based and volume-based pricing model

## Docs
- All covered cities: {base_url}/removals
- Privacy policy: {base_url}/privacy
- Terms of service: {base_url}/terms
"""


# ---------------------------------------------------------------------------
# Bing Webmaster Tools verification
# ---------------------------------------------------------------------------
@router.get("/BingSiteAuth.xml")
async def bing_site_auth():
    content = """<?xml version="1.0"?>
<users>
	<user>CE59AEC8DEB21F303FBC0D31BE9D3A69</user>
</users>"""
    return Response(content=content, media_type="application/xml")


# robots.txt
# ---------------------------------------------------------------------------
@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    base_url = settings.CANONICAL_DOMAIN.rstrip("/")
    return f"""User-agent: *
Allow: /
Allow: /removals/
Disallow: /survey/
Disallow: /admin/
Disallow: /company/
Disallow: /api/
Disallow: /webhooks/
Disallow: /health

# AI crawlers — allow indexing for GEO (Generative Engine Optimization)
User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Applebot-Extended
Allow: /

Sitemap: {base_url}/sitemap.xml
"""


# ---------------------------------------------------------------------------
# sitemap.xml
# ---------------------------------------------------------------------------
@router.get("/sitemap.xml")
async def sitemap_xml():
    base_url = settings.CANONICAL_DOMAIN.rstrip("/")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    urls = []

    # Homepage
    urls.append(f"""  <url>
    <loc>{base_url}/</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>""")

    # Removals index page
    urls.append(f"""  <url>
    <loc>{base_url}/removals</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>""")

    # llms.txt
    urls.append(f"""  <url>
    <loc>{base_url}/llms.txt</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>""")

    # City pages
    for slug in UK_CITIES:
        urls.append(f"""  <url>
    <loc>{base_url}/removals/{slug}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    # Route pages
    for from_slug, to_slug in POPULAR_ROUTES:
        urls.append(f"""  <url>
    <loc>{base_url}/removals/{from_slug}-to-{to_slug}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>""")

    # Static pages
    for page in ["privacy", "terms"]:
        urls.append(f"""  <url>
    <loc>{base_url}/{page}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>""")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    return Response(content=xml_content, media_type="application/xml")


# ---------------------------------------------------------------------------
# City OR Route landing page: /removals/{slug}
# Handles both city pages (e.g. /removals/london) and route pages
# (e.g. /removals/london-to-manchester) via a single path parameter.
# ---------------------------------------------------------------------------
@router.get("/removals/{slug}")
async def removals_page(slug: str, request: Request):
    # Check if this is a route page (contains "-to-")
    if "-to-" in slug:
        return await _route_landing(slug, request)
    return await _city_landing(slug, request)


async def _city_landing(city_slug: str, request: Request):
    city = UK_CITIES.get(city_slug)
    if not city:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="City not found")

    nearby = _get_nearby_cities(city_slug)
    routes = _get_routes_for_city(city_slug)
    base_url = settings.CANONICAL_DOMAIN.rstrip("/")

    return templates.TemplateResponse(
        "consumer/city_landing.html",
        {
            "request": request,
            "city": city,
            "city_slug": city_slug,
            "nearby_cities": nearby,
            "routes": routes,
            "all_cities": UK_CITIES,
            "base_url": base_url,
        },
    )


async def _route_landing(route_slug: str, request: Request):
    from_slug, to_slug = route_slug.split("-to-", 1)
    from_city = UK_CITIES.get(from_slug)
    to_city = UK_CITIES.get(to_slug)
    if not from_city or not to_city:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Route not found")

    distance = _estimate_route_distance(from_slug, to_slug)

    # Rough price estimates based on distance
    if distance < 50:
        price_low, price_high = 350, 800
    elif distance < 100:
        price_low, price_high = 500, 1200
    elif distance < 200:
        price_low, price_high = 700, 1800
    elif distance < 300:
        price_low, price_high = 900, 2500
    else:
        price_low, price_high = 1200, 3500

    # Related routes (other routes from same origin)
    related = []
    for fs, ts in POPULAR_ROUTES:
        if fs == from_slug and ts != to_slug:
            related.append({
                "from_slug": fs, "to_slug": ts,
                "from_name": UK_CITIES.get(fs, {}).get("name", fs.title()),
                "to_name": UK_CITIES.get(ts, {}).get("name", ts.title()),
                "url": f"/removals/{fs}-to-{ts}",
            })
    # Also add reverse route if exists
    reverse_exists = (to_slug, from_slug) in POPULAR_ROUTES

    base_url = settings.CANONICAL_DOMAIN.rstrip("/")

    return templates.TemplateResponse(
        "consumer/route_landing.html",
        {
            "request": request,
            "from_city": from_city,
            "to_city": to_city,
            "from_slug": from_slug,
            "to_slug": to_slug,
            "distance": distance,
            "price_low": price_low,
            "price_high": price_high,
            "related_routes": related[:6],
            "reverse_exists": reverse_exists,
            "all_cities": UK_CITIES,
            "base_url": base_url,
        },
    )


# ---------------------------------------------------------------------------
# City index page: /removals
# ---------------------------------------------------------------------------
@router.get("/removals")
async def removals_index(request: Request):
    """Index page listing all cities we cover — internal link hub."""
    base_url = settings.CANONICAL_DOMAIN.rstrip("/")

    # Group cities by region
    regions = {}
    for slug, city in sorted(UK_CITIES.items(), key=lambda x: x[1]["name"]):
        region = city["county"]
        if region not in regions:
            regions[region] = []
        regions[region].append({"slug": slug, **city})

    return templates.TemplateResponse(
        "consumer/removals_index.html",
        {
            "request": request,
            "regions": regions,
            "total_cities": len(UK_CITIES),
            "base_url": base_url,
        },
    )
