
def _get_openai_client() -> Optional[OpenAI]:
    """Initializes and returns the OpenAI client if the API key is available."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        print("WARNING OpenAI client not available. Please set OPENAI_API_KEY.")
        return None
    return OpenAI(api_key=api_key)

def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Calculates the cosine similarity between two numpy vectors.
    """
    dot_product = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    
    epsilon = 1e-8
    return dot_product / ((norm_a * norm_b) + epsilon)

async def _get_embeddings(texts: List[str], model: str = None):
    """
    Receives a list of texts and returns a tuple of (embedding_vectors, usage_dict).
    Optimized for batch processing with OpenAI API limits (max 2048 inputs per request).
    """
    # Get default embedding model from centralized config if not specified
    model = get_embedding_config("default")["model"]

    client = _get_openai_client()
    BATCH_SIZE = 2048 # OpenAI embedding API limit: 2048 inputs per request
    # Max Input tokens for each articleis 8192
    
    
    all_embeddings = []
    # total_usage = {"model": model, "prompt_tokens": 0, "total_tokens": 0, "completion_tokens": 0}
    
    # Process in batches if we have more than BATCH_SIZE texts
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        
        response = await asyncio.to_thread(
            client.embeddings.create, 
            input=batch_texts, 
            model=model
        )
        
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
        
        # # Accumulate usage statistics
        # total_usage["prompt_tokens"] += response.usage.prompt_tokens
        # total_usage["total_tokens"] += response.usage.total_tokens
    
    return all_embeddings#, total_usage
        
async def _rank_articles_by_embedding(
    articles: List[ArticleData], 
    raw_query: str,
    top_k: int,
    threshold: float,
    tracker: CostTracker,
    mode: str = "quick"
) -> List[ArticleData]:
    """
    Reranks a list of articles based on semantic similarity and logs the cost.
    """
    if not articles or not raw_query:
        return articles
        
    # ranking_start = time.time()
    # print(f"\nPerforming semantic ranking for {len(articles)} articles started at {datetime.now().strftime('%H:%M:%S')}...")

    article_texts = [f"Title: {a.get('title', '')}. Abstract: {a.get('abstract', '')}" for a in articles]
    all_texts_to_embed = [raw_query] + article_texts
    
    embedding_result = await _get_embeddings(all_texts_to_embed)

    # embeddings, usage = embedding_result
    embeddings = embedding_result
    # tracker.add_embedding_call("article_embedding", usage)
    
    # if len(embeddings) != len(all_texts_to_embed):
    #      print("WARNING Mismatch in embedding count. Returning articles without semantic ranking.")
    #      return articles

    query_embedding = np.array(embeddings[0])
    article_embeddings = [np.array(e) for e in embeddings[1:]]

    scored_articles = []
    for i, art_emb in enumerate(article_embeddings):
        score = _cosine_similarity(query_embedding, art_emb)
        articles[i]['relevance_score'] = score
        scored_articles.append(articles[i])
        
    scored_articles.sort(key=lambda a: a.get('relevance_score', 0.0), reverse=True)
    
    final_articles = [a for a in scored_articles if a.get('relevance_score', 0.0) >= threshold]
    
    print("Top article scores:")
    for i, a in enumerate(final_articles[:5], 1):
        score = a.get('relevance_score', 0.0)
        source = a.get('source', 'Unknown')
        title = a.get('title', 'No title')[:60] + ('...' if len(a.get('title', '')) > 60 else '')
        print(f"  {i}. [{source}] Score: {score:.3f} - {title}")
    
    return final_articles[:top_k]