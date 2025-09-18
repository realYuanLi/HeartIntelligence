import os
import openai
from dotenv import load_dotenv
from .web_search import web_search, format_search_results, needs_web_search
load_dotenv()

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

class Agent:
    
    def __init__(self, role, llm="",sys_message="",tool="",temperature=0.5,response_schema=None):
        self.role = role
        self.llm = llm
        self.temperature = temperature
        self.sys_message = sys_message
        self.response_schema = response_schema
        
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
            
            # Get the latest user message to check if web search is needed
            latest_user_message = None
            for msg in reversed(openai_messages):
                if msg.get("role") == "user":
                    latest_user_message = msg.get("content", "")
                    break
            
            # Use lightweight decision model to determine if web search is needed
            should_search = False
            search_query = ""
            
            if latest_user_message:
                should_search = needs_web_search(latest_user_message)
                if should_search:
                    search_query = latest_user_message
            
            if should_search:
                # Perform web search first
                print(f"Web search needed for query: {search_query}")
                search_results = web_search(search_query)
                formatted_results = format_search_results(search_results)
                
                # Add search results to the conversation
                openai_messages.append({
                    "role": "assistant",
                    "content": f"Let me search for current information about: {search_query}"
                })
                openai_messages.append({
                    "role": "user",
                    "content": f"Here are the search results:\n\n{formatted_results}\n\nPlease provide a comprehensive answer based on this information."
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
        # This would need to be implemented if you want to use local Llama
        # For now, fall back to OpenAI
        return self.openai_reply(messages)
    