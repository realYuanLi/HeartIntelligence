import os
import openai
import asyncio
import threading
import tiktoken
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from .web_search import web_search, format_search_results, needs_web_search
from .health_analyzer import analyze_health_query, analyze_health_query_with_raw_data
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

# Global status tracking
current_status = {"status": "idle"}
status_lock = threading.Lock()

def update_status(status):
    """Update the global status with thread safety."""
    with status_lock:
        current_status["status"] = status

def get_status():
    """Get the current status."""
    with status_lock:
        return current_status["status"]

class Agent:
    
    def __init__(self, role, llm="",sys_message="",tool="",temperature=0.5,response_schema=None,ehr_data=None,mobile_data=None):
        self.role = role
        self.llm = llm
        self.temperature = temperature
        self.sys_message = sys_message
        self.response_schema = response_schema
        self.ehr_data = ehr_data
        self.mobile_data = mobile_data
        
        # Define available LLM functions
        self.llm_name_list = {
            "gpt-5": self.openai_reply,
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
    
    
    def _web_search_task(self, query: str):
        """Task for web search analysis."""
        try:
            if needs_web_search(query):
                update_status("searching_web")
                search_results = web_search(query)
                update_status("analyzing_web_data")
                return {
                    'search_results': search_results,
                    'needs_search': True
                }
        except Exception as e:
            print(f"Web search error: {e}")
        return None
    
    def _health_analysis_task(self, query: str):
        """Task for health data analysis - includes patient profile and mobile health data."""
        try:
            import time
            start_time = time.time()
            
            needs_health, patient_profile, formatted_output, patient_data_formatted = analyze_health_query_with_raw_data(
                query, 
                self.ehr_data, 
                show_raw_data=True,
                mobile_data=self.mobile_data
            )
            
            elapsed = time.time() - start_time
            print(f"Health analysis completed in {elapsed:.2f} seconds")
            
            if needs_health:
                return {
                    'health_analysis': {
                        'needs_health': needs_health,
                        'patient_profile': patient_profile,
                        'formatted_output': formatted_output,
                        'patient_data_formatted': patient_data_formatted
                    }
                }
        except Exception as e:
            print(f"Health analysis error: {e}")
            import traceback
            traceback.print_exc()
        return None
        
    def openai_reply(self, messages):
        class Response:
            def __init__(self, content):
                self.content = content
        
        try:
            openai_messages = []
            for msg in messages:
                if msg.get("role") in ["user", "assistant", "system"]:
                    openai_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            latest_user_message = None
            for msg in reversed(openai_messages):
                if msg.get("role") == "user":
                    latest_user_message = msg.get("content", "")
                    break
            
            web_results = None
            health_results = None
            
            if latest_user_message:
                print(f"Running parallel analysis for query: {latest_user_message}")
                update_status("processing")
                web_results, health_results = self._parallel_analysis(latest_user_message)
            
            # Process data sources
            web_summary = None
            health_summary = None
            
            # Process web search results
            if web_results and web_results.get('needs_search'):
                search_results = web_results['search_results']
                formatted_results = format_search_results(search_results)
                web_summary = formatted_results
            
            # Process patient data - no summarization needed, data is small
            if health_results and health_results.get('health_analysis'):
                health_analysis = health_results['health_analysis']
                if health_analysis.get('patient_data_formatted'):
                    # Patient profile is small enough to include directly
                    health_summary = health_analysis['patient_data_formatted']
                elif health_analysis.get('formatted_output'):
                    health_summary = health_analysis['formatted_output']
            
            # Build intelligent response based on available sources
            if web_summary and health_summary:
                # Both sources available - integrate them
                openai_messages.append({
                    "role": "assistant",
                    "content": f"I'll analyze your query using both current medical information and your personal health data to provide you with the most relevant and accurate response."
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"""You are a personal health assistant that answers with specific guidance. You should be friendly, precise, and confidence-building. You may use current information and the user’s personal health data when they improve the answer.\nQuery: "{latest_user_message}"

CURRENT INFORMATION:
{web_summary}

PERSONAL HEALTH DATA:
{health_summary}

Provide the best possible answer to the user’s question. 
- If the question involves medications:
  - Include: indications, key ingredients/formulations (if available), manufacturer (if available).
  - Personalize when useful: link to the user’s conditions, allergies, current meds, renal/hepatic status, pregnancy, prior adverse events.
  - Add practical use: timing with meals, missed-dose handling, duration.

- If the question involves lab results:
  - Lead with abnormal values and classify severity versus reference ranges.
  - Provide multi-marker reasoning (patterns across related labs), not isolated one-by-one commentary.
  - Compare to baseline/trend when available; quantify changes.
  - Tie interpretations to relevant conditions/meds when helpful.
  - End with a short, prioritized action list (monitoring cadence, lifestyle focus, medication checks).

- If the question involves exercise:
  - Report dynamics when data exist: day-to-day and week-over-week trends (e.g., steps, minutes, HR zones, effort, pain/fatigue).
  - Set next-week targets with progression and recovery rules.
  - Personalize to conditions/meds when useful (e.g., asthma, hypertension, diabetes, joint pain; beta-blockers).
  - Specify what to track and thresholds to scale up/down.

- For other topics (nutrition, symptoms, sleep, etc.):
  - Connect recommendations to available context (web information and personal health data) when it improves precision.
  - For symptoms, outline likely mechanisms, self-care steps, what to monitor, and a time-box for recheck.

For web sources, use citation format [domain.com](url). Examples: [example.com](https://example.com/article) or [wikipedia.org](https://en.wikipedia.org/wiki/topic)."""
                })
            elif web_summary:
                # Only web search available
                openai_messages.append({
                    "role": "assistant",
                    "content": f"I'll search for current, evidence-based information to help answer your health question."
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"""You are a personal health assistant. You should be friendly, precise, and confidence-building.\nQuery: "{latest_user_message}"

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
                    "content": f"""You are a personal health assistant that answers with specific guidance. You should be friendly, precise, and confidence-building. You should use the user’s personal health data.\nQuery: "{latest_user_message}"

PERSONAL HEALTH DATA:
{health_summary}"

Provide the best possible answer to the user’s question. 
- If the question relates to medications:
  - Include: indications, key ingredients/formulations (if available), manufacturer (if available).
  - Personalize when useful: link to the user’s conditions, allergies, current meds, renal/hepatic status, pregnancy, prior adverse events.
  - Add practical use: timing with meals, missed-dose handling, duration.

- If the question relates to lab results:
  - Lead with abnormal values and classify severity versus reference ranges.
  - Provide multi-marker reasoning (patterns across related labs), not isolated one-by-one commentary.
  - Compare to baseline/trend when available; quantify changes.
  - Tie interpretations to relevant conditions/meds when helpful.
  - End with a short, prioritized action list (monitoring cadence, lifestyle focus, medication checks).

- If the question relates to exercise:
  - Report dynamics when data exist: day-to-day and week-over-week trends (e.g., steps, minutes, HR zones, effort, pain/fatigue).
  - Set next-week targets with progression and recovery rules.
  - Personalize to conditions/meds when useful (e.g., asthma, hypertension, diabetes, joint pain; beta-blockers).
  - Specify what to track and thresholds to scale up/down.

- For other topics (nutrition, symptoms, sleep, etc.):
  - Connect recommendations to available context (personal health data) when it improves precision.
  - For symptoms, outline likely mechanisms, self-care steps, what to monitor, and a time-box for recheck.
"""
                })
            
            # Use the configured model instead of hardcoded gpt-5
            final_model = self.llm
            
            api_params = {
                "model": final_model,
                "messages": openai_messages
            }
            
            # GPT-5 only supports temperature=1, other models support custom temperature
            if final_model != "gpt-5":
                api_params["temperature"] = self.temperature
            
            response = openai.chat.completions.create(**api_params)
            
            message = response.choices[0].message
            
            # Update status to complete
            update_status("idle")
            
            # Return response in expected format
            return Response(message.content)
        
        except Exception as e:
            error_msg = str(e)
            print(f"OpenAI API call failed: {e}")
            update_status("idle")
            
            # Check if it's an API key issue
            if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return Response("I'm having trouble connecting to the AI service. Please check that the OpenAI API key is configured correctly in the environment variables.")
            elif "rate_limit" in error_msg.lower():
                return Response("The AI service is currently experiencing high demand. Please try again in a moment.")
            else:
                return Response(f"I encountered an error while processing your request: {error_msg}. Please try again or contact support if the issue persists.")
    
    def llama_api_reply(self, messages):  
        return self.openai_reply(messages)
    