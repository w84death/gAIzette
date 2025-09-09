import feedparser
import requests
import os
import time
import re
from datetime import datetime
from html.parser import HTMLParser
import sys
import argparse

# Configuration:
# - Create a 'feeds.txt' file with one RSS feed URL per line (e.g., https://example.com/rss)
# - Create a 'topics.txt' file with one topic per line (e.g., AI\nTechnology\nScience)
# - Ollama server should be running on localhost:11434 (install and run via https://ollama.com)
# - Model: Change 'llama3' below if you prefer a different model
# - Output: Generates 'news.html' in the current directory

class ImageExtractor(HTMLParser):
    """Extract first image from HTML content."""
    def __init__(self):
        super().__init__()
        self.image_url = None

    def handle_starttag(self, tag, attrs):
        if tag == 'img' and not self.image_url:
            attrs_dict = dict(attrs)
            src = attrs_dict.get('src', '')

            # Skip if it looks like a tracking pixel or icon
            width = attrs_dict.get('width', '')
            height = attrs_dict.get('height', '')

            # Skip tiny images (likely tracking pixels or icons)
            try:
                if width and height:
                    if int(width) < 50 or int(height) < 50:
                        return
            except:
                pass

            # Skip if alt text suggests it's not a news image
            alt = attrs_dict.get('alt', '').lower()
            skip_alts = ['logo', 'icon', 'avatar', 'profile', 'share', 'twitter', 'facebook']
            if any(skip_word in alt for skip_word in skip_alts):
                return

            self.image_url = src

def extract_image_from_html(html_content):
    """Extract the first image URL from HTML content."""
    if not html_content:
        return None
    parser = ImageExtractor()
    parser.feed(html_content)
    return parser.image_url

def is_valid_news_image(url, debug=False):
    """Check if URL is likely a valid news image, not a logo or tracker."""
    if not url:
        return False

    url_lower = url.lower()

    if debug:
        print(f"           Checking image: {url[:80]}...")

    # Filter out common social media and tracking images
    excluded_patterns = [
        'twitter.com', 'x.com', 't.co',
        'facebook.com', 'fb.com',
        'instagram.com',
        'linkedin.com',
        'pinterest.com',
        'youtube.com',
        'doubleclick.net',
        'google-analytics.com',
        'feedburner.com',
        'feedblitz.com',
        'pixel', 'tracking', 'beacon',
        'avatar', 'logo', 'icon',
        'badge', 'button',
        '1x1', '0x0',  # Tracking pixels
        'spacer.gif', 'clear.gif', 'blank.gif',
        'share', 'social',
        'comment', 'rss',
        'ads.', 'ad.',
        'twitter-logo', 'fb-logo', 'x-logo'
    ]

    for pattern in excluded_patterns:
        if pattern in url_lower:
            if debug:
                print(f"           ❌ Rejected: contains '{pattern}'")
            return False

    # Check for image file extensions (good sign)
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']
    has_image_extension = any(ext in url_lower for ext in image_extensions)

    # If it doesn't have an image extension, be more strict
    if not has_image_extension:
        # Could still be valid if it's from a CDN or image service
        cdn_patterns = ['cdn', 'images', 'media', 'static', 'assets', 'upload']
        if not any(pattern in url_lower for pattern in cdn_patterns):
            if debug:
                print(f"           ❌ Rejected: no image extension or CDN pattern")
            return False

    if debug:
        print(f"           ✓ Valid news image")
    return True

def get_article_image(entry, debug=False):
    """Extract image URL from RSS entry using various methods."""
    candidates = []

    if debug:
        title = entry.get('title', 'Untitled')[:50]
        print(f"       🔍 Extracting image for: {title}...")

    # Try media:content or media:thumbnail
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            if media.get('type', '').startswith('image'):
                url = media.get('url')
                if is_valid_news_image(url, debug=debug):
                    # Prefer larger images if width/height available
                    width = media.get('width', 0)
                    height = media.get('height', 0)
                    candidates.append((url, width * height if width and height else 100000))

    if hasattr(entry, 'media_thumbnail'):
        for thumb in entry.media_thumbnail:
            url = thumb.get('url')
            if is_valid_news_image(url, debug=debug):
                width = thumb.get('width', 0)
                height = thumb.get('height', 0)
                # Thumbnails get lower priority
                candidates.append((url, width * height if width and height else 50000))

    # Try enclosures
    if hasattr(entry, 'enclosures'):
        for enclosure in entry.enclosures:
            if enclosure.get('type', '').startswith('image'):
                url = enclosure.get('href') or enclosure.get('url')
                if is_valid_news_image(url, debug=debug):
                    candidates.append((url, 75000))  # Medium priority

    # Try to extract from content or summary
    content = entry.get('content', [{}])[0].get('value', '') if hasattr(entry, 'content') else ''
    if content:
        # Extract all images from content
        parser = ImageExtractor()
        parser.feed(content)
        # Get first valid image
        if parser.image_url and is_valid_news_image(parser.image_url, debug=debug):
            candidates.append((parser.image_url, 60000))

    # Try summary/description as last resort
    if not candidates:
        summary = entry.get('summary', entry.get('description', ''))
        if summary:
            parser = ImageExtractor()
            parser.feed(summary)
            if parser.image_url and is_valid_news_image(parser.image_url, debug=debug):
                candidates.append((parser.image_url, 40000))

    # Return the best candidate (highest priority/size)
    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_url = candidates[0][0]

        # Final validation - make sure URL is absolute
        if not best_url.startswith(('http://', 'https://')):
            # Try to construct absolute URL if we have a base
            if hasattr(entry, 'link'):
                from urllib.parse import urljoin
                best_url = urljoin(entry.link, best_url)

        if debug:
            print(f"           Found {len(candidates)} image candidates")
            print(f"           Selected: {best_url[:80]}...")
        return best_url

    if debug:
        print(f"         No valid images found")
    return None

def clean_summary(summary):
    """Remove HTML tags from summary."""
    if not summary:
        return ""
    # Remove HTML tags
    clean = re.sub('<.*?>', '', summary)
    # Decode HTML entities
    clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # Remove extra whitespace
    clean = ' '.join(clean.split())
    return clean

def get_ollama_response(prompt, model=None):
    if model is None:
        if os.path.exists('model.txt'):
            with open('model.txt', 'r') as f:
                model = f.read().strip()
        else:
            model = 'gemma3:12b'
    """Query Ollama API for a response."""
    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False}
        )
        response.raise_for_status()
        return response.json()['response'].strip()
    except Exception as e:
        print(f"Error querying Ollama: {e}")
        return ""

def select_featured_stories(articles, model=None):
    """Use Ollama to select the most important stories for the cover."""
    if not articles:
        return []

    print("\n📰 Selecting featured stories with AI...")

    # Prepare article summaries for AI
    article_list = ""
    for i, article in enumerate(articles[:20]):  # Limit to first 20 for context window
        article_list += f"{i+1}. {article['title']}\n   {article['summary'][:200]}...\n\n"

    print(f"   Analyzing {min(20, len(articles))} articles for newsworthiness...")
    prompt = f"""You are a news editor selecting the most important and newsworthy stories for the front page.
From the following articles, select the 3-4 most important stories that should be featured prominently.
Consider factors like: global impact, breaking news, public interest, and significance.

Articles:
{article_list}

Return ONLY the numbers of the selected articles, separated by commas (e.g., "1,3,7,12").
Select between 3 and 4 articles maximum."""

    response = get_ollama_response(prompt, model)

    # Parse the response to get article indices
    featured_indices = []
    try:
        # Extract numbers from the response
        numbers = re.findall(r'\d+', response)
        for num in numbers[:4]:  # Max 4 featured stories
            idx = int(num) - 1  # Convert to 0-based index
            if 0 <= idx < len(articles):
                featured_indices.append(idx)
        print(f"   ✓ AI selected {len(featured_indices)} featured stories")
    except Exception as e:
        print(f"   ⚠️ Error parsing featured stories: {e}")
        # Fallback to first 3 articles
        featured_indices = [0, 1, 2] if len(articles) >= 3 else list(range(len(articles)))
        print(f"   Using fallback: first {len(featured_indices)} articles")

    return featured_indices

# Parse command line arguments
parser = argparse.ArgumentParser(description='gAIzette RSS Reader - AI-Curated News')
parser.add_argument('--debug-images', action='store_true', help='Enable detailed image extraction debugging')
parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
args = parser.parse_args()

# Load feeds and topics
print("=" * 60)
print("🚀 gAIzette RSS Reader - Starting...")
if args.debug_images:
    print("🔍 Image debugging enabled")
print("=" * 60)

print("\n📋 Loading configuration...")
if not os.path.exists('feeds.txt'):
    print("❌ Error: 'feeds.txt' not found. Create it with RSS URLs.")
    exit(1)
if not os.path.exists('topics.txt'):
    print("❌ Error: 'topics.txt' not found. Create it with topics.")
    exit(1)

feeds = [line.strip() for line in open('feeds.txt') if line.strip()]
topics = [line.strip() for line in open('topics.txt') if line.strip()]

if not feeds:
    print("❌ No feeds found in 'feeds.txt'.")
    exit(1)
if not topics:
    print("❌ No topics found in 'topics.txt'.")
    exit(1)

print(f"   ✓ Loaded {len(feeds)} RSS feeds")
print(f"   ✓ Loaded {len(topics)} topics: {', '.join(topics[:3])}{'...' if len(topics) > 3 else ''}")

# Check Ollama model
model = None
if os.path.exists('model.txt'):
    with open('model.txt', 'r') as f:
        model = f.read().strip()
        print(f"   ✓ Using Ollama model: {model}")
else:
    model = 'gemma3:12b'
    print(f"   ✓ Using default Ollama model: {model}")

# Fetch and filter articles
print("\n🔄 Processing RSS feeds...")
articles = []
total_articles_analyzed = 0
feed_count = 0

for feed_url in feeds:
    feed_count += 1
    print(f"\n   [{feed_count}/{len(feeds)}] Processing: {feed_url[:50]}{'...' if len(feed_url) > 50 else ''}")

    try:
        feed = feedparser.parse(feed_url)
        source_name = feed.feed.get('title', 'Unknown Source')
        print(f"       Source: {source_name}")
        print(f"       Found {len(feed.entries)} entries")

        filtered_count = 0
        articles_with_images = 0
        for entry in feed.entries:
            total_articles_analyzed += 1
            title = entry.get('title', 'Untitled')
            raw_summary = entry.get('summary', entry.get('description', ''))
            summary = clean_summary(raw_summary)
            link = entry.get('link', '#')
            pub_parsed = entry.get('published_parsed', None)
            pub_date = datetime(*pub_parsed[:6]).isoformat() if pub_parsed else datetime.now().isoformat()

            # Extract image (enable debug based on command line flag)
            debug_images = args.debug_images and total_articles_analyzed < 10  # Debug first 10 if flag set
            image_url = get_article_image(entry, debug=debug_images)
            if image_url:
                articles_with_images += 1

            # Show progress for every 10th article
            if total_articles_analyzed % 10 == 0:
                sys.stdout.write(f"\r       Analyzing articles... {total_articles_analyzed}")
                sys.stdout.flush()

            # Prepare prompt for Ollama
            prompt = (
                f"Topics of interest: {', '.join(topics)}\n"
                f"Article title: {title}\n"
                f"Article summary: {summary[:500]}...\n"  # Truncate summary to avoid token limits
                f"Does this article relate to any of the topics? Answer only 'yes' or 'no'."
            )

            response = get_ollama_response(prompt, model)
            if 'yes' in response.lower():
                filtered_count += 1
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'pub_date': pub_date,
                    'pub_parsed': pub_parsed,  # For sorting
                    'image_url': image_url,
                    'source': source_name
                })

        sys.stdout.write(f"\r       ✓ Filtered {filtered_count} relevant articles from {len(feed.entries)} total\n")
        if articles_with_images > 0 or args.verbose:
            print(f"       📷 Found images for {articles_with_images} articles")
        sys.stdout.flush()

    except Exception as e:
        print(f"       ❌ Error parsing feed: {e}")

print(f"\n📊 Summary:")
print(f"   Total articles analyzed: {total_articles_analyzed}")
print(f"   Articles matching topics: {len(articles)}")

# Count articles with images
articles_with_images_total = sum(1 for a in articles if a.get('image_url'))
print(f"   Articles with images: {articles_with_images_total}/{len(articles)}")

# Sort articles by publication date (newest first)
print("\n🔤 Sorting articles by date...")
articles.sort(
    key=lambda x: time.mktime(x['pub_parsed']) if x['pub_parsed'] else time.time(),
    reverse=True
)
print("   ✓ Articles sorted (newest first)")

# Select featured stories using AI
featured_indices = select_featured_stories(articles, model)
featured_articles = [articles[i] for i in featured_indices if i < len(articles)]
regular_articles = [articles[i] for i in range(len(articles)) if i not in featured_indices]

if featured_articles:
    print("\n⭐ Featured stories selected:")
    for i, article in enumerate(featured_articles, 1):
        print(f"   {i}. {article['title'][:60]}{'...' if len(article['title']) > 60 else ''}")

# Generate HTML with NY Times-inspired layout
print("\n🎨 Generating HTML...")
html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>gAIzette - Your AI-Curated News</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #fff;
            color: #121212;
            line-height: 1.6;
        }

        /* Header */
        header {
            border-bottom: 1px solid #dfdfdf;
            padding: 20px 0;
            margin-bottom: 20px;
        }

        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
            text-align: center;
        }

        header h1 {
            font-family: Chomsky, Georgia, 'Times New Roman', serif;
            font-size: 3.5em;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 10px;
        }

        @font-face {
            font-family: 'Chomsky';
            src: local('Georgia'), local('Times New Roman');
        }

        .date-line {
            font-size: 0.875rem;
            color: #666;
            margin-bottom: 10px;
        }

        .topics {
            font-size: 0.875rem;
            color: #666;
        }

        .topics-label {
            font-weight: 600;
            color: #333;
            margin-right: 5px;
        }

        /* Main Container */
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }

        /* Featured Section */
        .featured-section {
            margin-bottom: 40px;
            border-bottom: 2px solid #121212;
            padding-bottom: 30px;
        }

        .featured-header {
            font-size: 1.125rem;
            font-weight: 700;
            color: #121212;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .featured-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
            margin-bottom: 20px;
        }

        .featured-article {
            border-right: 1px solid #dfdfdf;
            padding-right: 30px;
        }

        .featured-article:last-child {
            border-right: none;
            padding-right: 0;
        }

        .featured-article .article-image {
            width: 100%;
            height: 250px;
            object-fit: cover;
            margin-bottom: 15px;
            background-color: #f0f0f0;
        }

        .featured-article h2 {
            font-size: 1.5rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 10px;
        }

        .featured-article h2 a {
            color: #121212;
            text-decoration: none;
        }

        .featured-article h2 a:hover {
            text-decoration: underline;
        }

        .featured-article .summary {
            font-size: 1rem;
            line-height: 1.5;
            color: #363636;
            margin-bottom: 10px;
        }

        .article-meta {
            font-size: 0.75rem;
            color: #727272;
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .article-source {
            font-weight: 600;
            text-transform: uppercase;
        }

        /* Regular Articles Section */
        .articles-section {
            margin-bottom: 40px;
        }

        .section-header {
            font-size: 1rem;
            font-weight: 700;
            color: #121212;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #dfdfdf;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .articles-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 30px;
        }

        .article {
            padding-bottom: 20px;
            border-bottom: 1px solid #e2e2e2;
        }

        .article-with-image {
            display: flex;
            gap: 15px;
        }

        .article .article-image-small {
            width: 100px;
            height: 100px;
            object-fit: cover;
            flex-shrink: 0;
            background-color: #f0f0f0;
        }

        .article-content {
            flex: 1;
        }

        .article h3 {
            font-size: 1.125rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 8px;
        }

        .article h3 a {
            color: #121212;
            text-decoration: none;
        }

        .article h3 a:hover {
            text-decoration: underline;
        }

        .article .summary {
            font-size: 0.875rem;
            line-height: 1.4;
            color: #5a5a5a;
            margin-bottom: 8px;
        }

        /* Responsive Design */
        @media (max-width: 768px) {
            header h1 {
                font-size: 2.5em;
            }

            .featured-grid {
                grid-template-columns: 1fr;
            }

            .featured-article {
                border-right: none;
                padding-right: 0;
                border-bottom: 1px solid #dfdfdf;
                padding-bottom: 20px;
                margin-bottom: 20px;
            }

            .featured-article:last-child {
                border-bottom: none;
            }

            .articles-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Footer */
        footer {
            border-top: 2px solid #121212;
            margin-top: 60px;
            padding: 30px 0;
            text-align: center;
            color: #666;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            <h1>gAIzette</h1>
            <div class="date-line">""" + datetime.now().strftime('%A, %B %d, %Y') + """</div>
            <div class="topics">
                <span class="topics-label">Following:</span>
                """ + ', '.join(topics) + """
            </div>
        </div>
    </header>

    <div class="container">
"""

# Add featured articles section if available
if featured_articles:
    html += """
        <section class="featured-section">
            <h2 class="featured-header">Top Stories</h2>
            <div class="featured-grid">
"""

    for article in featured_articles:
        image_html = ""
        if article.get('image_url'):
            image_html = f'<img src="{article["image_url"]}" alt="" class="article-image" onerror="this.style.display=\'none\'">'

        # Format date
        try:
            dt = datetime.fromisoformat(article['pub_date'].replace('Z', '+00:00'))
            formatted_date = dt.strftime('%I:%M %p').lstrip('0')
        except:
            formatted_date = "Recently"

        html += f"""
                <article class="featured-article">
                    {image_html}
                    <h2><a href="{article['link']}">{article['title']}</a></h2>
                    <p class="summary">{article['summary'][:250]}...</p>
                    <div class="article-meta">
                        <span class="article-source">{article['source']}</span>
                        <span>•</span>
                        <span>{formatted_date}</span>
                    </div>
                </article>
"""

    html += """
            </div>
        </section>
"""

# Add regular articles section
if regular_articles:
    html += """
        <section class="articles-section">
            <h2 class="section-header">More News</h2>
            <div class="articles-grid">
"""

    for article in regular_articles[:20]:  # Limit to 20 regular articles
        image_html = ""
        article_class = "article"

        if article.get('image_url'):
            image_html = f'<img src="{article["image_url"]}" alt="" class="article-image-small" onerror="this.style.display=\'none\'">'
            article_class = "article article-with-image"

        # Format date
        try:
            dt = datetime.fromisoformat(article['pub_date'].replace('Z', '+00:00'))
            formatted_date = dt.strftime('%I:%M %p').lstrip('0')
        except:
            formatted_date = "Recently"

        if image_html:
            html += f"""
                <div class="article">
                    <div class="article-with-image">
                        {image_html}
                        <div class="article-content">
                            <h3><a href="{article['link']}">{article['title']}</a></h3>
                            <p class="summary">{article['summary'][:150]}...</p>
                            <div class="article-meta">
                                <span class="article-source">{article['source']}</span>
                                <span>•</span>
                                <span>{formatted_date}</span>
                            </div>
                        </div>
                    </div>
                </div>
"""
        else:
            html += f"""
                <div class="article">
                    <h3><a href="{article['link']}">{article['title']}</a></h3>
                    <p class="summary">{article['summary'][:150]}...</p>
                    <div class="article-meta">
                        <span class="article-source">{article['source']}</span>
                        <span>•</span>
                        <span>{formatted_date}</span>
                    </div>
                </div>
"""

    html += """
            </div>
        </section>
"""

html += """
    </div>

    <footer>
        <div class="container">
            <p>© """ + str(datetime.now().year) + """ gAIzette - AI-Curated News Reader</p>
            <p>Generated on """ + datetime.now().strftime('%B %d, %Y at %I:%M %p') + """</p>
            <p>Total articles analyzed: """ + str(len(articles)) + """ | Featured: """ + str(len(featured_articles)) + """</p>
        </div>
    </footer>
</body>
</html>
"""

# Write to file
print("   Writing HTML to file...")
with open('news.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("\n" + "=" * 60)
print("✅ SUCCESS!")
print("=" * 60)
print(f"📄 Generated 'news.html' with:")
print(f"   • {len(featured_articles)} featured stories")
print(f"   • {len(regular_articles)} regular articles")
print(f"   • {len(articles)} total articles")
print(f"\n🌐 Open 'news.html' in your browser to view your personalized news!")
if args.debug_images:
    print(f"\n💡 Tip: Run without --debug-images for cleaner output")
print("=" * 60)
