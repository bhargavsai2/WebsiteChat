from bs4 import BeautifulSoup
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.core.cache import cache
import hashlib
from urllib.parse import urljoin, urlparse

# Global settings
MAX_DEPTH = 2  # Limit the depth of crawling
USER_AGENT = "Mozilla/5.0 (compatible; WebChatUI/1.0;)"

def fetch_page_content(url):
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return ""


def extract_links(base_url, html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # Resolve relative URLs
        full_url = urljoin(base_url, href)
        # Keep only links within the same domain
        if urlparse(full_url).netloc == urlparse(base_url).netloc:
            links.add(full_url)
    return links


def crawl_website(base_url, max_depth):
    visited = set()
    to_visit = [(base_url, 0)]  # (url, depth)
    content_accumulator = []

    while to_visit:
        current_url, depth = to_visit.pop(0)
        if depth > max_depth or current_url in visited:
            continue

        visited.add(current_url)
        print(f"Scraping: {current_url}")
        html_content = fetch_page_content(current_url)
        if not html_content:
            continue

        # Extract text content
        soup = BeautifulSoup(html_content, 'html.parser')
        content_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'article', 'section', 'main'])
        page_content = ' '.join([elem.get_text(strip=True) for elem in content_elements])
        content_accumulator.append(page_content)

        # Extract links and add to the queue
        links = extract_links(base_url, html_content)
        for link in links:
            if link not in visited:
                to_visit.append((link, depth + 1))

    return " ".join(content_accumulator)

def query_ollama(content, query):
    try:
        ollama_api_url = "http://localhost:11434/api/generate"
        
        # Prepare the context by truncating if too long
        max_context_length = 4000  # Adjust based on your model's context window
        if len(content) > max_context_length:
            content = content[:max_context_length] + "..."
        
        prompt = f"""Based on the following website content, please answer the question.
        If you cannot find relevant information to answer the question, say so.
        
        Content: {content}
        
        Question: {query}
        
        Answer:"""
        
        payload = {
            "model": "llama3.2",
            "prompt": prompt,
            "stream": False,
            "temperature": 0.7
        }
        
        response = requests.post(ollama_api_url, json=payload)
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        raise Exception(f"Ollama query failed: {str(e)}")


@csrf_exempt
def query_view(request):
    if request.method != "POST":
        return JsonResponse({'error': 'Invalid request method.'}, status=405)
        
    try:
        body = json.loads(request.body)
        url = body.get('url')
        query = body.get('query')

        if not url or not query:
            return JsonResponse({'error': 'URL and query are required.'}, status=400)
            
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_key = f'website_content_{url_hash}'
        
        cached_content = cache.get(cache_key)
        
        if not cached_content or query == 'initial_scrape':
            # Crawl the entire website
            all_content = crawl_website(url, MAX_DEPTH)
            cache.set(cache_key, all_content, 3600)

            if query == 'initial_scrape':
                return JsonResponse({
                    'message': 'Website content scraped successfully',
                    'pages_crawled': len(all_content.split('\n')),  # Approximate page count
                })
        else:
            all_content = cached_content

        # Query Ollama with the content
        ollama_response = query_ollama(all_content, query)

        return JsonResponse({
            'response': ollama_response.get('response', 'No response received'),
            'source': url
        })

    except requests.RequestException as e:
        return JsonResponse({'error': f'Failed to fetch the website: {str(e)}'}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'An unexpected error occurred: {str(e)}'}, status=500)