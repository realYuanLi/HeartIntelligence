from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv
load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

class Agent:
    
    def __init__(self, role, llm="",sys_message="",tool="",temperature=0.5,response_schema=None):
        self.role = role
        self.llm = llm
        self.temperature =temperature
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
            self.llm_reply = self.llm_name_list[self.llm]  # Call the method here
        else:
            raise ValueError(f"Unknown LLM: {self.llm}")
        
        
    def openai_reply(self, messages):
        llm_model = ChatOpenAI(
            model=self.llm,
            temperature=self.temperature
        )
        
        try:
            if self.response_schema is None:
                llm_langchain = llm_model 
            else:
                llm_langchain = llm_model.with_structured_output(self.response_schema, include_raw=True)
            return llm_langchain.invoke(messages)
        
        except Exception as e:
            print(f"LLM invocation failed: {e}")
            return None
    
    
    
    def llama_api_reply(self,messages):  
        llm_model = ChatOpenAI(
            model="/home/local/PARTNERS/ys670/Medical_FM/Huggingface/Meta-Llama-3.1-70B-Instruct-AWQ-INT4",
            base_url="http://10.162.9.148:8000/v1",
            temperature=self.temperature
            ) 

        return llm_model.invoke(messages)
    
       