import feedparser
import requests
import os
import time
import re
from datetime import datetime
import sys

# Configuration:
# - Create a 'feeds.txt' file with one RSS feed URL per line (e.g., https://example.com/rss)
# - Create a 'topics.txt' file with one topic per line (e.g., AI\nTechnology\nScience)
# - Ollama server should be running on localhost:11434 (install and run via https://ollama.com)
# - Model: Change 'llama3' below if you prefer a different model
# - Output: Generates 'news.html' in the current directory

def clean_summary(summary):
    """Remove HTML tags from summary."""
    if not summary:
        return ""
    # Remove HTML tags
    clean = re.sub('<.*?>', '', summary)
    # Decode HTML entities
    clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'")
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

# Load feeds and topics
print("=" * 60)
print("🚀 gAIzette RSS Reader - Starting...")
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
        for entry in feed.entries:
            total_articles_analyzed += 1
            title = entry.get('title', 'Untitled')
            raw_summary = entry.get('summary', entry.get('description', ''))
            summary = clean_summary(raw_summary)
            link = entry.get('link', '#')
            pub_parsed = entry.get('published_parsed', None)
            pub_date = datetime(*pub_parsed[:6]).isoformat() if pub_parsed else datetime.now().isoformat()

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
                    'source': source_name
                })

        sys.stdout.write(f"\r       ✓ Filtered {filtered_count} relevant articles from {len(feed.entries)} total\n")
        sys.stdout.flush()

    except Exception as e:
        print(f"       ❌ Error parsing feed: {e}")

print(f"\n📊 Summary:")
print(f"   Total articles analyzed: {total_articles_analyzed}")
print(f"   Articles matching topics: {len(articles)}")

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
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
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

        .featured-article h2 {
            font-size: 1.75rem;
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
            font-size: 1.05rem;
            line-height: 1.5;
            color: #363636;
            margin-bottom: 12px;
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
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 30px;
        }

        .article {
            padding-bottom: 20px;
            border-bottom: 1px solid #e2e2e2;
        }

        .article h3 {
            font-size: 1.25rem;
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
            font-size: 0.95rem;
            line-height: 1.45;
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
            <h1><img src="gaizette.svg">gAIzette</img></h1>
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
        # Format date
        try:
            dt = datetime.fromisoformat(article['pub_date'].replace('Z', '+00:00'))
            formatted_date = dt.strftime('%I:%M %p').lstrip('0')
        except:
            formatted_date = "Recently"

        html += f"""
                <article class="featured-article">
                    <h2><a href="{article['link']}">{article['title']}</a></h2>
                    <p class="summary">{article['summary'][:350]}...</p>
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
        # Format date
        try:
            dt = datetime.fromisoformat(article['pub_date'].replace('Z', '+00:00'))
            formatted_date = dt.strftime('%I:%M %p').lstrip('0')
        except:
            formatted_date = "Recently"

        html += f"""
                <div class="article">
                    <h3><a href="{article['link']}">{article['title']}</a></h3>
                    <p class="summary">{article['summary'][:200]}...</p>
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
print("=" * 60)
