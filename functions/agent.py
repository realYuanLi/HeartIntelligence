from langchain_openai import ChatOpenAI
from langchain_openai import AzureChatOpenAI
import os

os.environ["AZURE_OPENAI_ENDPOINT"] = "https://mgh-camca-research-private-e2-openai-service.openai.azure.com/"
os.environ["AZURE_OPENAI_API_KEY"] = "1ed375af719f4293acc9b389e3758819"

os.environ["OPENAI_API_KEY"] = "token-abc123"   # for mgh local model

class Agent:
    
    def __init__(self, role, llm="",sys_message="",tool="",temperature=0.5,response_schema=None):
        self.role = role
        self.llm = llm
        self.temperature =temperature
        self.sys_message = sys_message
        self.response_schema = response_schema
        
        # Define available LLM functions
        self.llm_name_list = {
            "azure_gpt_4o_2024_8_6": self.azure_gpt_reply,
            "azure_gpt_4o_2024_11_20": self.azure_gpt_reply,
            "azure_gpt_4o_mini": self.azure_gpt_reply,
            "azure_gpt_o3_mini": self.azure_gpt_o_reply,
            "azure_gpt_41": self.azure_gpt_reply,
            "azure_gpt_41_mini": self.azure_gpt_reply,
            "azure_gpt_41_nano":self.azure_gpt_reply,
            "llama3.1_api": self.llama_api_reply
        }

        # Assign LLM function or handle unknown LLM
        if self.llm in self.llm_name_list:
            self.llm_reply = self.llm_name_list[self.llm]  # Call the method here
        else:
            raise ValueError(f"Unknown LLM: {self.llm}")
        
        
        
    def azure_gpt_reply(self,messages): 
        
        llm_config = {
            "azure_gpt_4o_mini": ("test_gpt_4o_mini", "2024-08-01-preview"),
            "azure_gpt_4o_2024_8_6": ("gpt_4o_2024_8_6_r", "2024-08-01-preview"),
            "azure_gpt_4o_2024_11_20": ("gpt_4o_2024_11_20_g", "2024-08-01-preview"),
            "azure_gpt_41": ("gpt_41_2025_04_14","2025-01-01-preview"),
            "azure_gpt_41_mini": ("gpt_41_mini_2025_04_14","2025-01-01-preview"),
            "azure_gpt_41_nano":("gpt_41_nano_2025_04_14","2025-01-01-preview"),
        }
        
        deployment, version = llm_config[self.llm]
          
        llm_model = AzureChatOpenAI(
            azure_deployment= deployment,
            api_version= version,
            temperature=self.temperature,
            max_tokens=None
        )
        
        try:
            if self.response_schema is None:
                llm_langchain= llm_model 
            else:
                llm_langchain = llm_model.with_structured_output(self.response_schema,include_raw=True) #,include_raw=True
            return llm_langchain.invoke(messages)
        
        except Exception as e:
            print(f"LLM invocation failed: {e}")
            # Optionally: raise or return a fallback
            return None
    
        
    
    
    def azure_gpt_o_reply(self,messages): 
        
        if self.llm == "azure_gpt_o3_mini":
            deployment="gpt_o3_mini_2025_01_31"
            version="2024-12-01-preview"

        llm_model = AzureChatOpenAI(
            azure_deployment= deployment,
            api_version= version,
            reasoning_effort="medium"  ##low, medium, and high
            # max_tokens=None
        )
        
        try:
            if self.response_schema is None:
                llm_langchain= llm_model 
            else:
                llm_langchain = llm_model.with_structured_output(self.response_schema,include_raw=True) #,include_raw=True
            return llm_langchain.invoke(messages)
        
        except Exception as e:
            print(f"LLM invocation failed: {e}")
            # Optionally: raise or return a fallback
            return None
    
    
    
    def llama_api_reply(self,messages):  
        llm_model = ChatOpenAI(
            model="/home/local/PARTNERS/ys670/Medical_FM/Huggingface/Meta-Llama-3.1-70B-Instruct-AWQ-INT4",
            base_url="http://10.162.9.148:8000/v1",
            temperature=self.temperature
            ) 

        return llm_model.invoke(messages)
    
       