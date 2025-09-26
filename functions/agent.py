import os
import openai
import threading
import tiktoken
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from .web_search import web_search, format_search_results, needs_web_search
from .health_analyzer import analyze_health_query, analyze_health_query_with_raw_data
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

class Agent:
    
    def __init__(self, role, llm="",sys_message="",tool="",temperature=0.5,response_schema=None,ehr_data=None):
        self.role = role
        self.llm = llm
        self.temperature = temperature
        self.sys_message = sys_message
        self.response_schema = response_schema
        self.ehr_data = ehr_data
        
        # Define available LLM functions
        self.llm_name_list = {
            "gpt-4o": self.openai_reply,
            "gpt-4o-mini": self.openai_reply,
            "gpt-4-turbo": self.openai_reply,
            "gpt-3.5-turbo": self.openai_reply,
            "llama3.1_api": self.llama_api_reply
        }

        if self.llm in self.llm_name_list:
            self.llm_reply = self.llm_name_list[self.llm]
        else:
            raise ValueError(f"Unknown LLM: {self.llm}")
    
    def _parallel_analysis(self, query: str):
        """
        Run web search and health data analysis in parallel.
        
        Args:
            query (str): The user's query
            
        Returns:
            Tuple: (web_search_results, health_analysis_results)
        """
        web_results = None
        health_results = None
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both tasks
            web_future = executor.submit(self._web_search_task, query)
            health_future = executor.submit(self._health_analysis_task, query)
            
            # Collect results as they complete
            for future in as_completed([web_future, health_future]):
                try:
                    result = future.result()
                    if result is not None:
                        if 'search_results' in result:
                            web_results = result
                        elif 'health_analysis' in result:
                            health_results = result
                except Exception as e:
                    print(f"Error in parallel task: {e}")
        
        return web_results, health_results
    
    def _count_tokens(self, text: str, model: str = "gpt-4o") -> int:
        """Count tokens in text using tiktoken."""
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except:
            # Fallback: rough estimation (1 token ≈ 4 characters)
            return len(text) // 4
    
    def _split_text_by_tokens(self, text: str, max_tokens: int, model: str = "gpt-4o") -> list:
        """Split text into chunks that don't exceed max_tokens."""
        try:
            encoding = tiktoken.encoding_for_model(model)
            tokens = encoding.encode(text)
            chunks = []
            for i in range(0, len(tokens), max_tokens):
                chunk_tokens = tokens[i:i + max_tokens]
                chunk_text = encoding.decode(chunk_tokens)
                chunks.append(chunk_text)
            return chunks
        except:
            # Fallback: split by characters
            chunk_size = max_tokens * 4  # rough estimation
            return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    
    def _summarize_chunk(self, chunk: str, category: str) -> str:
        """Summarize a single chunk of health data."""
        try:
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": f"Create a concise, clinically relevant summary of this {category} data. Include key metrics, dates, trends, medications, conditions, and important findings. Focus on clinically significant information and exclude administrative data like ID numbers."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this {category} data, focusing on clinically relevant information and patterns:\n\n{chunk}"
                    }
                ],
                temperature=0.1,
                max_tokens=10000
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error summarizing chunk: {e}")
            return f"[Summary unavailable for {category} chunk]"
    
    def _summarize_health_data(self, raw_data_output: str, max_tokens_per_chunk: int = 10000) -> str:
        """Summarize health data, splitting into chunks if necessary."""
        if not raw_data_output or raw_data_output == "No raw data available.":
            return "No health data available for summarization."
        
        # Count total tokens
        total_tokens = self._count_tokens(raw_data_output)
        
        # If data is small enough, summarize directly
        if total_tokens <= max_tokens_per_chunk:
            try:
                response = openai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": "Create a concise, clinically relevant summary of this health data. Include key metrics, dates, trends, medications, conditions, and important findings. Focus on clinically significant information and exclude administrative data like ID numbers."
                        },
                        {
                            "role": "user",
                            "content": f"Summarize this health data, focusing on clinically relevant information and patterns:\n\n{raw_data_output}"
                        }
                    ],
                    temperature=0.1,
                    max_tokens=16000
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"Error summarizing health data: {e}")
                return raw_data_output
        
        # Split into chunks and summarize in parallel
        chunks = self._split_text_by_tokens(raw_data_output, max_tokens_per_chunk)
        
        # Extract category from the data for better context
        category = "health data"
        if "CATEGORY:" in raw_data_output:
            lines = raw_data_output.split('\n')
            for line in lines:
                if line.startswith("CATEGORY:"):
                    category = line.replace("CATEGORY:", "").strip()
                    break
        
        # Summarize chunks in parallel
        summaries = []
        with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as executor:
            future_to_chunk = {executor.submit(self._summarize_chunk, chunk, category): chunk for chunk in chunks}
            
            for future in as_completed(future_to_chunk):
                try:
                    summary = future.result()
                    summaries.append(summary)
                except Exception as e:
                    print(f"Error in parallel summarization: {e}")
                    summaries.append("[Summary chunk failed]")
        
        # Combine summaries
        combined_summary = "\n\n".join(summaries)
        
        # Final summary of summaries if still too long
        if self._count_tokens(combined_summary) > 15000:
            try:
                response = openai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": "Create a final, concise summary by combining these health data summaries. Focus on the most clinically significant findings, key trends, current status, and areas needing attention. Maintain clinical accuracy while providing a complete health overview."
                        },
                        {
                            "role": "user",
                            "content": f"Create a final, comprehensive summary from these health data summaries, focusing on the most clinically relevant information:\n\n{combined_summary}"
                        }
                    ],
                    temperature=0.1,
                    max_tokens=10000
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"Error in final summarization: {e}")
                return combined_summary
        
        return combined_summary
    
    def _web_search_task(self, query: str):
        """Task for web search analysis."""
        try:
            if needs_web_search(query):
                search_results = web_search(query)
                return {
                    'search_results': search_results,
                    'needs_search': True
                }
        except Exception as e:
            print(f"Web search error: {e}")
        return None
    
    def _health_analysis_task(self, query: str):
        """Task for health data analysis."""
        try:
            needs_health, categories, formatted_output, raw_data_output = analyze_health_query_with_raw_data(query, self.ehr_data, show_raw_data=True)
            if needs_health:
                return {
                    'health_analysis': {
                        'needs_health': needs_health,
                        'categories': categories,
                        'formatted_output': formatted_output,
                        'raw_data_output': raw_data_output
                    }
                }
        except Exception as e:
            print(f"Health analysis error: {e}")
        return None
        
    def openai_reply(self, messages):
        # Define Response class at the beginning
        class Response:
            def __init__(self, content):
                self.content = content
        
        try:
            # Convert messages to OpenAI format
            openai_messages = []
            for msg in messages:
                if msg.get("role") in ["user", "assistant", "system"]:
                    openai_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            # Get the latest user message for parallel analysis
            latest_user_message = None
            for msg in reversed(openai_messages):
                if msg.get("role") == "user":
                    latest_user_message = msg.get("content", "")
                    break
            
            # Run parallel analysis if we have a user message
            web_results = None
            health_results = None
            
            if latest_user_message:
                print(f"Running parallel analysis for query: {latest_user_message}")
                web_results, health_results = self._parallel_analysis(latest_user_message)
            
            # Process and summarize data sources
            web_summary = None
            health_summary = None
            
            # Process web search results
            if web_results and web_results.get('needs_search'):
                search_results = web_results['search_results']
                formatted_results = format_search_results(search_results)
                web_summary = formatted_results
            
            # Process health data analysis results
            if health_results and health_results.get('health_analysis'):
                health_analysis = health_results['health_analysis']
                if health_analysis.get('raw_data_output'):
                    # Summarize health data
                    health_summary = self._summarize_health_data(health_analysis['raw_data_output'])
                elif health_analysis.get('formatted_output'):
                    health_summary = f"Available Health Data Categories:\n{health_analysis['formatted_output']}"
            
            # Build intelligent response based on available sources
            if web_summary and health_summary:
                # Both sources available - integrate them
                openai_messages.append({
                    "role": "assistant",
                    "content": f"I'll analyze your query using both current medical information and your personal health data to provide you with the most relevant and accurate response."
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"""Query: "{latest_user_message}"

CURRENT MEDICAL INFORMATION:
{web_summary}

PERSONAL HEALTH DATA:
{health_summary}

Provide a comprehensive answer that integrates both current information and personal health data. Reference specific values and trends from their data. Use citation format [domain.com](url). Examples: [example.com](https://example.com/article) or [wikipedia.org](https://en.wikipedia.org/wiki/topic). Include medical disclaimers about consulting healthcare providers."""
                })
            elif web_summary:
                # Only web search available
                openai_messages.append({
                    "role": "assistant",
                    "content": f"I'll search for current, evidence-based information to help answer your health question."
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"""Query: "{latest_user_message}"

CURRENT MEDICAL INFORMATION:
{web_summary}

Provide an accurate, evidence-based answer based on this information. Use citation format [domain.com](url). Examples: [example.com](https://example.com/article) or [wikipedia.org](https://en.wikipedia.org/wiki/topic). Include relevant safety information and medical disclaimers about consulting healthcare providers."""
                })
            elif health_summary:
                # Only health data available
                openai_messages.append({
                    "role": "assistant",
                    "content": f"I'll analyze your personal health data to provide insights relevant to your question."
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"""Query: "{latest_user_message}"

PERSONAL HEALTH DATA:
{health_summary}

Analyze this health data thoroughly, referencing specific values and trends. Provide insights and actionable recommendations. Include medical disclaimers about consulting healthcare providers for medical decisions."""
                })
            
            # Make API call without tools (since we've already done the search if needed)
            response = openai.chat.completions.create(
                model=self.llm,
                messages=openai_messages,
                temperature=self.temperature
            )
            
            message = response.choices[0].message
            
            # Return response in expected format
            return Response(message.content)
        
        except Exception as e:
            print(f"OpenAI API call failed: {e}")
            return None
    
    def llama_api_reply(self, messages):  
        return self.openai_reply(messages)
    