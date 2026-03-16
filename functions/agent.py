import json
import os
import openai
import asyncio
import threading
import tiktoken
from dotenv import load_dotenv
from .skills_runtime import SkillRuntime
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
        self.skill_runtime = SkillRuntime(ehr_data=ehr_data, mobile_data=mobile_data)
        
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
    
    # Tool definition for workout plan management
    WORKOUT_PLAN_TOOL = {
        "type": "function",
        "function": {
            "name": "manage_workout_plan",
            "description": "Create, modify, or view the user's workout plan, or mark a workout as complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "modify", "view", "complete_today", "complete_date"],
                        "description": "The action to perform on the workout plan"
                    },
                    "details": {
                        "type": "string",
                        "description": "Request details: plan description for create, modification request for modify, or date (YYYY-MM-DD) for complete_date"
                    }
                },
                "required": ["action"]
            }
        }
    }

    # Tool definition for exercise search
    EXERCISE_TOOL = {
        "type": "function",
        "function": {
            "name": "exercise_search",
            "description": "Search the exercise database for workouts, exercises by muscle group, equipment, or difficulty. Use this whenever the user asks about exercises, workouts, or fitness routines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query describing what exercises to find, e.g. 'chest exercises with dumbbells' or 'beginner leg workout'"
                    }
                },
                "required": ["query"]
            }
        }
    }

    # Tool definition for nutrition management
    NUTRITION_TOOL = {
        "type": "function",
        "function": {
            "name": "manage_nutrition",
            "description": (
                "Create, modify, or view the user's meal plan, grocery list, nutrition profile, or nutrient gaps. "
                "IMPORTANT: When the user reveals personal nutrition-relevant facts in conversation "
                "(weight, height, age, sex, allergies, dietary preferences like vegetarian/vegan/keto, "
                "health goals like weight loss, activity level, budget), call this tool with action "
                "'extract_insights' and details as a JSON object of the extracted fields. Field names: "
                "age, weight_kg, height_cm, sex, activity_level, allergies (array), dietary_preferences "
                "(array), health_goals (array), weekly_budget_usd. Include a _snippets object mapping "
                "field names to the exact user quote. You may call extract_insights alongside your "
                "normal response."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create_plan", "modify_plan", "view_plan", "grocery_list", "update_profile", "nutrient_check", "extract_insights"],
                        "description": "The action to perform on the nutrition plan or profile"
                    },
                    "details": {
                        "type": "string",
                        "description": "Plan description, modification request, profile fields as JSON, or for extract_insights a JSON object with extracted fields and optional _snippets mapping"
                    }
                },
                "required": ["action"]
            }
        }
    }

    def _get_username_from_messages(self, messages):
        """Extract username from system message metadata if available."""
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str) and "Username:" in content:
                    for line in content.split("\n"):
                        if line.strip().startswith("Username:"):
                            return line.split("Username:", 1)[1].strip()
        return ""

    def _execute_exercise_search(self, query):
        """Run exercise search and return text summary + image markdown separately."""
        from .workout_search import search_exercises, ensure_exercise_image
        exercises = search_exercises(query)
        if not exercises:
            return None, []

        # Build text-only summary for the LLM (no image markdown)
        sections = []
        image_lines = []
        for i, ex in enumerate(exercises, 1):
            name = ex.get("name", "Unknown")
            level = ex.get("level", "N/A").capitalize()
            category = ex.get("category", "N/A").capitalize()
            equipment = (ex.get("equipment") or "None").capitalize()
            primary = ", ".join(m.capitalize() for m in ex.get("primaryMuscles", []))
            secondary = ", ".join(m.capitalize() for m in ex.get("secondaryMuscles", []))
            instructions = ex.get("instructions", [])
            images = ex.get("images", [])

            section = f"### {i}. {name}\n"
            section += f"**{level} | {category} | {equipment}**\n"
            section += f"Targets: {primary}"
            if secondary:
                section += f" (also: {secondary})"
            section += "\n"

            if instructions:
                section += "\n**How to:**\n"
                for step_num, step in enumerate(instructions, 1):
                    section += f"{step_num}. {step}\n"

            sections.append(section)

            # Collect image data separately
            if images:
                img_path = images[0]
                ensure_exercise_image(img_path)
                image_lines.append({"name": name, "url": f"/exercises/images/{img_path}"})

        text_summary = f"**Exercise Database — {len(exercises)} results:**\n\n"
        text_summary += "\n---\n\n".join(sections)
        return text_summary, image_lines

    def openai_reply(self, messages):
        class Response:
            def __init__(self, content, exercise_images=None):
                self.content = content
                self.exercise_images = exercise_images or []

        try:
            openai_messages = []
            for msg in messages:
                if msg.get("role") not in ["user", "assistant", "system"]:
                    continue
                images = msg.get("images") or []
                if images and msg["role"] == "user":
                    # Build multi-part content for vision API
                    parts = []
                    if msg["content"]:
                        parts.append({"type": "text", "text": msg["content"]})
                    for data_uri in images:
                        parts.append({"type": "image_url", "image_url": {"url": data_uri}})
                    openai_messages.append({"role": "user", "content": parts})
                else:
                    openai_messages.append({"role": msg["role"], "content": msg["content"]})

            latest_user_message = None
            for msg in reversed(openai_messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        latest_user_message = " ".join(
                            p["text"] for p in content if p.get("type") == "text"
                        )
                    else:
                        latest_user_message = content
                    break

            # Run non-tool context skills (web search, health data)
            context_sections = []
            if latest_user_message:
                print(f"Running skill runtime for query: {latest_user_message}")
                update_status("processing")
                skill_results = self.skill_runtime.run(
                    query=latest_user_message,
                    kind="context",
                    runtime_context={},
                    status_updater=update_status,
                )
                web_output = skill_results.get("web_search", {})
                health_output = skill_results.get("personal_health_context", {})

                if web_output.get("activated") and web_output.get("web_summary"):
                    context_sections.append(f"CURRENT INFORMATION:\n{web_output['web_summary']}")
                if health_output.get("activated") and health_output.get("health_summary"):
                    context_sections.append(f"PERSONAL HEALTH DATA:\n{health_output['health_summary']}")

                exam_output = skill_results.get("physical_exam_interpreter", {})
                if exam_output.get("activated") and exam_output.get("exam_summary"):
                    exam_context = "PHYSICAL EXAM FINDINGS REFERENCE (use ONLY this data — do not add outside associations):\n"
                    exam_context += exam_output["exam_summary"]
                    context_sections.append(exam_context)

                if context_sections:
                    combined = "\n\n".join(context_sections)
                    openai_messages.append({
                        "role": "user",
                        "content": f'Query: "{latest_user_message}"\n\n{combined}\n\nAnswer the query using the above information. Follow your system instructions.'
                    })

            # Use the configured model
            final_model = self.llm

            api_params = {
                "model": final_model,
                "messages": openai_messages,
                "tools": [self.EXERCISE_TOOL, self.WORKOUT_PLAN_TOOL, self.NUTRITION_TOOL],
            }

            # GPT-5 only supports temperature=1
            if final_model != "gpt-5":
                api_params["temperature"] = self.temperature

            response = openai.chat.completions.create(**api_params)
            message = response.choices[0].message

            # Handle tool calls
            exercise_images = []
            if message.tool_calls:
                # Append the assistant message with tool calls
                openai_messages.append(message)

                for tool_call in message.tool_calls:
                    if tool_call.function.name == "exercise_search":
                        args = json.loads(tool_call.function.arguments)
                        query = args.get("query", latest_user_message or "")
                        update_status("searching_exercises")

                        text_summary, exercise_images = self._execute_exercise_search(query)

                        tool_result = text_summary or "No exercises found for that query."
                        tool_result += "\n\n[Present concisely — name, sets/reps, schedule only. No full instructions unless asked.]"
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                    elif tool_call.function.name == "manage_workout_plan":
                        args = json.loads(tool_call.function.arguments)
                        action = args.get("action", "view")
                        details = args.get("details", "")
                        update_status("processing")

                        # Get username from conversation metadata or system context
                        username = self._get_username_from_messages(openai_messages)

                        from .workout_plans import handle_workout_plan_tool
                        tool_result = handle_workout_plan_tool(action, details, username)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                    elif tool_call.function.name == "manage_nutrition":
                        args = json.loads(tool_call.function.arguments)
                        action = args.get("action", "view_plan")
                        details = args.get("details", "")
                        update_status("processing")

                        username = self._get_username_from_messages(openai_messages)

                        from .nutrition_plans import handle_nutrition_tool
                        tool_result = handle_nutrition_tool(action, details, username)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                # Second LLM call with tool results
                update_status("processing")
                followup_params = {
                    "model": final_model,
                    "messages": openai_messages,
                }
                if final_model != "gpt-5":
                    followup_params["temperature"] = self.temperature

                response = openai.chat.completions.create(**followup_params)
                message = response.choices[0].message

            reply_text = message.content or ""

            update_status("idle")
            return Response(reply_text, exercise_images=exercise_images)

        except Exception as e:
            error_msg = str(e)
            print(f"OpenAI API call failed: {e}")
            update_status("idle")

            if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return Response("I'm having trouble connecting to the AI service. Please check that the OpenAI API key is configured correctly in the environment variables.")
            elif "rate_limit" in error_msg.lower():
                return Response("The AI service is currently experiencing high demand. Please try again in a moment.")
            else:
                return Response(f"I encountered an error while processing your request: {error_msg}. Please try again or contact support if the issue persists.")
    
    def llama_api_reply(self, messages):  
        return self.openai_reply(messages)
    