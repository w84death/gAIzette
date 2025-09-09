import feedparser
import requests
import os
import time
from datetime import datetime

# Configuration:
# - Create a 'feeds.txt' file with one RSS feed URL per line (e.g., https://example.com/rss)
# - Create a 'topics.txt' file with one topic per line (e.g., AI\nTechnology\nScience)
# - Ollama server should be running on localhost:11434 (install and run via https://ollama.com)
# - Model: Change 'llama3' below if you prefer a different model
# - Output: Generates 'news.html' in the current directory

def get_ollama_response(prompt, model='gemma3:12b'):
    """Query Ollama API for a response."""
    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False}
        )
        response.raise_for_status()
        return response.json()['response'].strip().lower()
    except Exception as e:
        print(f"Error querying Ollama: {e}")
        return ""

# Load feeds and topics
if not os.path.exists('feeds.txt'):
    print("Error: 'feeds.txt' not found. Create it with RSS URLs.")
    exit(1)
if not os.path.exists('topics.txt'):
    print("Error: 'topics.txt' not found. Create it with topics.")
    exit(1)

feeds = [line.strip() for line in open('feeds.txt') if line.strip()]
topics = [line.strip() for line in open('topics.txt') if line.strip()]

if not feeds:
    print("No feeds found in 'feeds.txt'.")
    exit(1)
if not topics:
    print("No topics found in 'topics.txt'.")
    exit(1)

# Fetch and filter articles
articles = []
for feed_url in feeds:
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            title = entry.get('title', 'Untitled')
            summary = entry.get('summary', entry.get('description', ''))
            link = entry.get('link', '#')
            pub_parsed = entry.get('published_parsed', None)
            pub_date = datetime(*pub_parsed[:6]).isoformat() if pub_parsed else datetime.now().isoformat()

            # Prepare prompt for Ollama
            prompt = (
                f"Topics of interest: {', '.join(topics)}\n"
                f"Article title: {title}\n"
                f"Article summary: {summary[:500]}...\n"  # Truncate summary to avoid token limits
                f"Does this article relate to any of the topics? Answer only 'yes' or 'no'."
            )

            response = get_ollama_response(prompt)
            if 'yes' in response:
                articles.append({
                    'title': title,
                    'summary': summary,
                    'link': link,
                    'pub_date': pub_date,
                    'pub_parsed': pub_parsed  # For sorting
                })
    except Exception as e:
        print(f"Error parsing feed {feed_url}: {e}")

# Sort articles by publication date (newest first)
articles.sort(
    key=lambda x: time.mktime(x['pub_parsed']) if x['pub_parsed'] else time.time(),
    reverse=True
)

# Generate HTML with newspaper layout
html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>gAIzette</title>
    <style>
        body {
            font-family: 'Georgia', serif;
            background-color: #f4f4f4;
            color: #333;
            margin: 0;
            padding: 20px;
        }
        header {
            text-align: center;
            margin-bottom: 20px;
            border-bottom: 2px solid #000;
            padding-bottom: 10px;
        }
        header h1 {
            font-size: 3em;
            margin: 0;
            font-weight: bold;
            letter-spacing: 2px;
        }
        .topics {
            font-size: 0.8em;
            color: #666;
            margin-top: 10px;
        }
        .topics details {
            display: inline-block;
        }
        .topics summary {
            cursor: pointer;
            font-style: italic;
        }
        .topics ul {
            list-style-type: none;
            padding: 0;
            margin: 5px 0 0 0;
        }
        .topics li {
            margin-bottom: 5px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            column-count: 3;
            column-gap: 40px;
            column-rule: 1px solid #ccc;
        }
        .article {
            break-inside: avoid-column;
            margin-bottom: 30px;
        }
        .article h2 {
            font-size: 1.4em;
            margin: 0 0 5px;
            line-height: 1.2;
            font-weight: bold;
        }
        .article h2 a {
            color: #000;
            text-decoration: none;
        }
        .article h2 a:hover {
            text-decoration: underline;
        }
        .article .date {
            font-size: 0.8em;
            color: #666;
            margin-bottom: 10px;
            font-style: italic;
        }
        .article p {
            font-size: 1em;
            line-height: 1.5;
            margin: 0;
        }
        .article hr {
            border: none;
            border-top: 1px solid #ccc;
            margin: 20px 0 0 0;
        }
        @media (max-width: 768px) {
            .container {
                column-count: 1;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>gAIzette</h1>
        <div class="topics">
            <details>
                <summary>Topics Followed</summary>
                <ul>
"""

for topic in topics:
    html += f"                    <li>{topic}</li>\n"

html += """
                </ul>
            </details>
        </div>
    </header>
    <div class="container">
"""

for i, article in enumerate(articles):
    html += f"""
        <div class="article">
            <h2><a href="{article['link']}">{article['title']}</a></h2>
            <div class="date">{article['pub_date']}</div>
            <p>{article['summary'][:300]}...</p>
    """
    if i < len(articles) - 1:
        html += "            <hr>\n"
    html += "        </div>\n"

html += """
    </div>
</body>
</html>
"""

# Write to file
with open('news.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Generated 'news.html' with {len(articles)} articles.")
