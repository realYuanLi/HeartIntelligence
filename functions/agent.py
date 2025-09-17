import os
import openai
from dotenv import load_dotenv
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
        try:
            # Convert messages to OpenAI format
            openai_messages = []
            for msg in messages:
                if msg.get("role") in ["user", "assistant", "system"]:
                    openai_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            # Make API call
            response = openai.chat.completions.create(
                model=self.llm,
                messages=openai_messages,
                temperature=self.temperature
            )
            
            # Return response in expected format
            class Response:
                def __init__(self, content):
                    self.content = content
            
            return Response(response.choices[0].message.content)
        
        except Exception as e:
            print(f"OpenAI API call failed: {e}")
            return None
    
    def llama_api_reply(self, messages):  
        # This would need to be implemented if you want to use local Llama
        # For now, fall back to OpenAI
        return self.openai_reply(messages)
    
       