import os
import openai
from typing import Dict, Any, List, Annotated
import json
import re
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

def needs_web_search(query: str) -> bool:
    """
    Use a lightweight model to determine if a query requires web search.
    
    Args:
        query (str): The user's query
        
    Returns:
        bool: True if web search is needed, False otherwise
    """
    try:
        client = openai.OpenAI()
        
        # Use a very lightweight model for quick decision making
        response = client.chat.completions.create(
            model="gpt-4o",  # Fast and cheap model
            messages=[
                {
                    "role": "system",
                    "content": """You are a decision maker. Determine if a user query requires web search to answer accurately. When uncertain, default to YES since usually retrieving information from the web is helpful.

Return ONLY "YES" for:
- Current clinical guidelines, drug info, recalls, vaccines
- Recent research, trials, safety alerts
- Real-time data, current events, live information
- Location/provider-specific details

Return ONLY "NO" for:
- Simple questions that can be answered without web search

Examples:
- "Current COVID vaccine schedule" → YES
- "What is hypertension?" → NO
- "Drug recalls this month" → YES
- "How to take blood pressure" → NO"""
                },
                {
                    "role": "user",
                    "content": f"Query: {query}"
                }
            ],
            temperature=0,  # Low temperature for consistent decisions
            max_tokens=3
        )
        
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
        
    except Exception as e:
        logger.error(f"Error in needs_web_search: {e}")
        return True

def _extract_urls_from_metadata(message) -> List[str]:
    """Extract URLs from message metadata if available."""
    try:
        if hasattr(message, 'metadata') and message.metadata:
            urls = []
            for item in message.metadata.get('citations', []):
                if 'url' in item:
                    urls.append(item['url'])
            return urls
    except Exception:
        pass
    return []

def _extract_urls_from_text(text: str) -> List[str]:
    """Extract URLs from text using regex."""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)

def _clean_urls(urls: List[str]) -> List[str]:
    """Clean and deduplicate URLs."""
    if not urls:
        return []
    
    cleaned = []
    seen = set()
    
    for url in urls:
        # Remove trailing punctuation and clean up
        url = url.rstrip('.,;!?)')
        
        # Remove common tracking parameters
        tracking_params = ['utm_source=openai', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'gclid']
        for param in tracking_params:
            if f'?{param}' in url:
                url = url.replace(f'?{param}', '')
            elif f'&{param}' in url:
                url = url.replace(f'&{param}', '')
        
        # Clean up any remaining double separators
        url = url.replace('?&', '?').replace('&&', '&')
        if url.endswith('?'):
            url = url[:-1]
        
        # Ensure URL is valid and not seen before
        if url and url.startswith('http') and url not in seen:
            cleaned.append(url)
            seen.add(url)
    
    return cleaned

def openai_search_tool(
    query: Annotated[str, "The search query to send to OpenAI."],
) -> Dict[str, Any]:
    """
    Run a web search via OpenAI and return:
        {
          "query":  str,
          "answer": str,
          "urls":   List[str]   # unique, cleaned
        }
    """
    try:
        client = openai.OpenAI()

        completion = client.chat.completions.create(
            model="gpt-4o-search-preview",
            web_search_options={"search_context_size": "high"},
            messages=[{"role": "user", "content": query}],
        )

        msg = completion.choices[0].message
        answer = msg.content
        urls = _extract_urls_from_metadata(msg) or _extract_urls_from_text(answer)
        urls = _clean_urls(urls)

        # Extract journal name from answer
        journal = ""
        patterns = [
            r'Published in: ([^\n]+)',
            r'Journal: ([^\n]+)',
            r'Published by ([^\n]+)',
            r'Source: ([^\n]+)'
        ]
        for pat in patterns:
            match = re.search(pat, answer)
            if match:
                journal = match.group(1).strip()
                break

        return {
            "query": query,
            "answer": answer,
            "journal": journal,
            "urls": urls
        }

    except Exception as exc:
        error = f"OpenAI search failed: {exc!r}"
        logger.error(error)
        return {"error": error}

def web_search(query: str) -> Dict[str, Any]:
    """
    Perform web search using OpenAI's web search tool.
    
    Args:
        query (str): The search query string
    Returns:
        Dict containing search results with sources
    """
    return openai_search_tool(query)

def format_search_results(search_results: Dict[str, Any]) -> str:
    """
    Format search results for display in the chat with in-text citations.
    
    Args:
        search_results (Dict): The search results from web_search
    Returns:
        str: Formatted search results with in-text citations
    """
    if "error" in search_results:
        return f"Search error: {search_results['error']}"
    
    answer = search_results.get("answer", "No answer found")
    urls = search_results.get("urls", [])
    journal = search_results.get("journal", "")
    
    # Add in-text citations to the answer
    answer_with_citations = _add_in_text_citations(answer, urls)
    
    formatted = f"**Search Results:**\n\n{answer_with_citations}\n\n"
    
    if urls:
        # Extract domain from the first URL for source display
        try:
            first_url = urls[0]
            if '://' in first_url:
                domain = first_url.split('://')[1].split('/')[0]
            else:
                domain = first_url.split('/')[0]
            # Clean up domain (remove www, etc.)
            domain = domain.replace('www.', '')
            formatted += f"**Source:** {domain}\n\n"
        except:
            # Fallback to journal if URL parsing fails
            if journal:
                formatted += f"**Source:** {journal}\n\n"
    
    return formatted

def _add_in_text_citations(text: str, urls: List[str]) -> str:
    """
    Add domain-based citations to the text content based on URLs.
    
    Args:
        text (str): The original text content
        urls (List[str]): List of URLs to cite
    Returns:
        str: Text with in-text citations added using domain names
    """
    if not urls or not text:
        return text
    
    # Check if the text already contains proper citations
    if '[http' in text or '](http' in text:
        # Text already has citations, just return as is
        return text
    
    # If no citations found, add them at the end
    citation_text = "\n\n**Sources:**\n"
    for i, url in enumerate(urls[:3], 1):  # Limit to first 3 URLs
        try:
            # Extract domain from URL
            if '://' in url:
                domain = url.split('://')[1].split('/')[0]
            else:
                domain = url.split('/')[0]
            
            # Clean up domain (remove www, subdomains, etc.)
            domain = domain.replace('www.', '')
            
            # Handle common subdomains that should be removed
            subdomains_to_remove = ['m.', 'mobile.', 'en.', 'www.', 'api.', 'blog.', 'news.', 'support.']
            for subdomain in subdomains_to_remove:
                if domain.startswith(subdomain):
                    domain = domain[len(subdomain):]
                    break
            
            # Ensure domain is not empty and has proper format
            if domain and '.' in domain:
                citation_text += f"{i}. [{domain}]({url})\n"
            else:
                citation_text += f"{i}. {url}\n"
        except Exception as e:
            logger.warning(f"Error processing URL {url}: {e}")
            citation_text += f"{i}. {url}\n"
    
    return text + citation_text