import os
import openai
import threading
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

        # Assign LLM function or handle unknown LLM
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
            
            # Process web search results
            if web_results and web_results.get('needs_search'):
                search_results = web_results['search_results']
                formatted_results = format_search_results(search_results)
                
                # Add search results to the conversation
                openai_messages.append({
                    "role": "assistant",
                    "content": f"Let me search for current information about: {latest_user_message}"
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"Here are the search results:\n\n{formatted_results}\n\nPlease provide a comprehensive answer based on this information. IMPORTANT: When referencing sources, use the exact citation format [domain.com](url) where 'domain.com' is the website domain and 'url' is the full URL. Do NOT use parentheses around citations like ([domain.com](url)). Examples: [example.com](https://example.com/article) or [wikipedia.org](https://en.wikipedia.org/wiki/topic)."
                })
            
            # Process health data analysis results
            if health_results and health_results.get('health_analysis'):
                health_analysis = health_results['health_analysis']
                if health_analysis.get('formatted_output'):
                    # Add health data information to the conversation
                    openai_messages.append({
                        "role": "assistant",
                        "content": f"Let me analyze what health data is available for your query."
                    })
                    
                    # Include both formatted categories and raw data
                    health_content = f"Available Health Data Categories:\n{health_analysis['formatted_output']}"
                    
                    if health_analysis.get('raw_data_output'):
                        health_content += f"\n\nRaw Health Data Extracted:\n{health_analysis['raw_data_output']}"
                    
                    health_content += "\n\nPlease provide a comprehensive answer based on this actual health data. Include specific details from the raw data when relevant."
                    
                    openai_messages.append({
                        "role": "user",
                        "content": health_content
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
    