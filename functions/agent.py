import json
import logging
import os
import openai
import asyncio
import threading
import tiktoken
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
from .skills_runtime import SkillRuntime
from .agentic_loop import LoopState, make_reflection_message, summarize_tool_result, REFLECTION_CONTENT
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
            "description": "Create, modify, or view the user's workout plan, or mark a workout as complete. Plans cover ONE week only. When creating a plan, present a brief overview first and ask if the user wants to adjust before showing full details. Do not auto-repeat plans across multiple weeks.",
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
            "description": "Search the exercise database for workouts, exercises by muscle group, equipment, or difficulty. Use this whenever the user asks about exercises, workouts, or fitness routines. When presenting results, mention the source briefly (e.g. 'Based on the Free Exercise DB').",
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

    # Tool definition for user memory management
    MEMORY_TOOL = {
        "type": "function",
        "function": {
            "name": "manage_memory",
            "description": "Remember or forget user preferences, facts, and goals. Call 'remember' when the user reveals a preference, allergy, personal fact, or goal. Call 'forget' when the user asks to remove a stored fact. Call 'recall' to check what is remembered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["remember", "forget", "recall"]},
                    "category": {"type": "string", "enum": ["preference", "fact", "saved", "goal"], "description": "Memory category (required for remember)"},
                    "value": {"type": "string", "description": "The fact or preference to remember"},
                    "key": {"type": "string", "description": "Key of memory entry to forget"},
                    "notes": {"type": "string", "description": "Optional additional context or nuance"},
                    "context": {"type": "string", "description": "Why this memory matters and when to apply it, e.g. 'Important for meal planning — user avoids all animal products'"},
                    "evergreen": {"type": "boolean", "description": "Set true for core identity facts that should always be surfaced: allergies, chronic conditions, dietary restrictions, name. Default false."}
                },
                "required": ["action"]
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
                "Meal plans cover ONE week only. When creating a plan, present a brief overview first and ask "
                "if the user wants to adjust before showing full day-by-day details. Do not auto-repeat plans "
                "across multiple weeks. "
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

    TOOLS = [EXERCISE_TOOL, WORKOUT_PLAN_TOOL, NUTRITION_TOOL, MEMORY_TOOL]

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
                image_lines.append({
                    "name": name,
                    "url": f"/exercises/images/{img_path}",
                    "level": level,
                    "equipment": equipment,
                    "muscles": primary,
                })

        text_summary = f"**Exercise Database — {len(exercises)} results:**\n\n"
        text_summary += "\n---\n\n".join(sections)
        text_summary += "\n\n_Source: [Free Exercise DB](https://github.com/yuhonas/free-exercise-db) — open-source exercise database_"
        return text_summary, image_lines

    def _execute_tool_call(self, tool_call, openai_messages):
        """Execute a single tool call and return (result_text, exercise_images).

        Handles: exercise_search, manage_workout_plan, manage_nutrition, manage_memory.
        """
        exercise_images = []
        func_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Invalid JSON in tool call arguments for %s: %s", func_name, e)
            return f"Tool error: invalid arguments JSON — {e}", exercise_images

        if func_name == "exercise_search":
            query = args.get("query", "")
            update_status("searching_exercises")
            text_summary, exercise_images = self._execute_exercise_search(query)
            tool_result = text_summary or "No exercises found for that query."
            tool_result += "\n\n[Present concisely — name, sets/reps, schedule only. No full instructions unless asked.]"

        elif func_name == "manage_workout_plan":
            action = args.get("action", "view")
            details = args.get("details", "")
            update_status("processing")
            username = self._get_username_from_messages(openai_messages)
            from .workout_plans import handle_workout_plan_tool
            tool_result = handle_workout_plan_tool(action, details, username)

        elif func_name == "manage_nutrition":
            action = args.get("action", "view_plan")
            details = args.get("details", "")
            update_status("processing")
            username = self._get_username_from_messages(openai_messages)
            from .nutrition_plans import handle_nutrition_tool
            tool_result = handle_nutrition_tool(action, details, username)

        elif func_name == "manage_memory":
            action = args.get("action", "recall")
            update_status("processing")
            username = self._get_username_from_messages(openai_messages)
            from .user_memory import UserMemory
            try:
                mem = UserMemory(username)
                if action == "remember":
                    category = args.get("category", "fact")
                    value = args.get("value", "")
                    key = args.get("key")
                    notes = args.get("notes")
                    context = args.get("context")
                    evergreen = args.get("evergreen", False)
                    if not value:
                        tool_result = "Error: value is required to remember something."
                    else:
                        entry = mem.remember(category, value, key=key, notes=notes,
                                             context=context, evergreen=evergreen)
                        tool_result = f"Remembered: [{category}] {value} (key: {entry['key']})"
                elif action == "forget":
                    key = args.get("key", "")
                    found = mem.forget(key)
                    tool_result = f"Forgotten: {key}" if found else f"No memory found with key: {key}"
                else:  # recall
                    summary = mem.get_summary(max_items=15)
                    tool_result = summary if summary else "No memories stored for this user yet."
            except Exception as e:
                tool_result = f"Memory error: {e}"

        else:
            tool_result = f"Unknown tool: {func_name}"

        return tool_result, exercise_images

    def _make_llm_call(self, final_model, openai_messages, include_tools=True):
        """Make a single OpenAI chat completion call."""
        api_params = {
            "model": final_model,
            "messages": openai_messages,
        }
        if include_tools:
            api_params["tools"] = self.TOOLS
        if final_model != "gpt-5":
            api_params["temperature"] = self.temperature
        return openai.chat.completions.create(**api_params)

    def _drop_old_tool_messages(self, openai_messages, keep_iterations):
        """Remove tool role messages older than keep_iterations iterations back.

        Each iteration boundary is an assistant message with tool_calls followed
        by one or more tool messages.  We keep the last *keep_iterations* such
        groups and all non-tool messages.
        """
        # Identify iteration boundaries: indices of assistant messages that have tool_calls
        boundaries = []
        for idx, msg in enumerate(openai_messages):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            if role == "assistant" and tool_calls:
                boundaries.append(idx)

        if len(boundaries) <= keep_iterations:
            return openai_messages

        # Determine the cut-off: keep from boundaries[-keep_iterations] onward
        cutoff = boundaries[-keep_iterations]

        # Keep everything before the first boundary (system/user/context messages)
        # plus everything from cutoff onward
        preserved = []
        for idx, msg in enumerate(openai_messages):
            if idx < boundaries[0]:
                preserved.append(msg)
            elif idx >= cutoff:
                preserved.append(msg)
        return preserved

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

            # Extract images from the latest user message for skill context
            latest_user_images = []
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    latest_user_images = msg.get("images") or []
                    break

            # Run non-tool context skills (web search, health data)
            context_sections = []
            if latest_user_message or latest_user_images:
                skill_query = latest_user_message or "[image]"
                print(f"Running skill runtime for query: {skill_query}")
                update_status("processing")
                context_runtime = {"user": self._get_username_from_messages(openai_messages)}
                if latest_user_images:
                    context_runtime["images"] = latest_user_images
                skill_results = self.skill_runtime.run(
                    query=skill_query,
                    kind="context",
                    runtime_context=context_runtime,
                    status_updater=update_status,
                )
                web_output = skill_results.get("web_search", {})
                health_output = skill_results.get("personal_health_context", {})

                if web_output.get("activated") and web_output.get("web_summary"):
                    context_sections.append(f"CURRENT INFORMATION:\n{web_output['web_summary']}")
                if health_output.get("activated") and health_output.get("health_summary"):
                    context_sections.append(f"PERSONAL HEALTH DATA:\n{health_output['health_summary']}")

                health_qa_output = skill_results.get("health_qa", {})
                if health_qa_output.get("activated") and health_qa_output.get("health_qa_summary"):
                    health_qa_context = (
                        "HEALTH REFERENCE INFORMATION (from MedlinePlus/NIH):\n"
                        "Instructions: Use this reference data to give a warm, clear answer. "
                        "Structure your response with brief sections. Lead with the key takeaway. "
                        "Include the medical disclaimer naturally at the end. "
                        "If follow-up questions are suggested below, present 2-3 of them at the end "
                        "so the user can keep exploring. Cite the MedlinePlus source link.\n\n"
                    )
                    health_qa_context += health_qa_output["health_qa_summary"]
                    context_sections.append(health_qa_context)

                exam_output = skill_results.get("physical_exam_interpreter", {})
                if exam_output.get("activated") and exam_output.get("exam_summary"):
                    exam_context = "PHYSICAL EXAM FINDINGS REFERENCE (use ONLY this data — do not add outside associations):\n"
                    exam_context += exam_output["exam_summary"]
                    context_sections.append(exam_context)

                calendar_output = skill_results.get("external_calendar", {})
                if calendar_output.get("activated") and calendar_output.get("calendar_summary"):
                    calendar_context = (
                        "USER'S UPCOMING SCHEDULE (from their connected calendars):\n"
                        "Use this to avoid scheduling conflicts and suggest free time slots.\n\n"
                    )
                    calendar_context += calendar_output["calendar_summary"]
                    context_sections.append(calendar_context)

                food_image_output = skill_results.get("food_image_analysis", {})
                if food_image_output.get("activated") and food_image_output.get("food_image_summary"):
                    food_context = (
                        "FOOD IMAGE ANALYSIS (from user's photo):\n"
                        "Present this analysis conversationally. Include the item breakdown, "
                        "meal total with calorie range, daily budget comparison if available, "
                        "and suggestions.\n\n"
                    )
                    food_context += food_image_output["food_image_summary"]
                    context_sections.append(food_context)

                if context_sections:
                    combined = "\n\n".join(context_sections)
                    openai_messages.append({
                        "role": "user",
                        "content": f'Query: "{latest_user_message}"\n\n{combined}\n\nAnswer the query using the above information. Follow your system instructions.'
                    })

            # Use the configured model
            final_model = self.llm

            # First LLM call
            response = self._make_llm_call(final_model, openai_messages)
            message = response.choices[0].message

            # After first LLM call, if tool_calls present, enter reactive loop
            exercise_images = []
            if message.tool_calls:
                state = LoopState(max_iterations=8)

                while message.tool_calls:
                    # Append assistant message
                    openai_messages.append(message)

                    # Execute all tool calls
                    for tool_call in message.tool_calls:
                        try:
                            tool_result, tc_images = self._execute_tool_call(tool_call, openai_messages)
                        except Exception as e:
                            logger.warning("Tool call %s failed: %s", tool_call.function.name, e, exc_info=True)
                            tool_result = f"Tool error: {str(e)}"
                            tc_images = []

                        exercise_images.extend(tc_images)

                        # Progressive summarization (iteration 2+)
                        if state.iteration >= 2:
                            tool_result = summarize_tool_result(tool_result)

                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                    state.iteration += 1

                    # Progressive pruning (iteration 2+)
                    if state.iteration >= 2:
                        openai_messages = self._drop_old_tool_messages(openai_messages, keep_iterations=2)

                    # Reflection nudge (iteration 1+) — deduplicate
                    reflection = make_reflection_message(state.iteration)
                    if reflection:
                        openai_messages = [
                            m for m in openai_messages
                            if not (isinstance(m, dict) and m.get("content") == REFLECTION_CONTENT)
                        ]
                        openai_messages.append(reflection)

                    # Max iterations — force final answer
                    if state.iteration >= state.max_iterations:
                        update_status("processing")
                        response = self._make_llm_call(final_model, openai_messages, include_tools=False)
                        message = response.choices[0].message
                        break

                    # Next LLM call
                    update_status("processing")
                    response = self._make_llm_call(final_model, openai_messages)
                    message = response.choices[0].message

            reply_text = message.content or ""

            # Track conversation topic in short-term memory
            if latest_user_message:
                try:
                    username = self._get_username_from_messages(openai_messages)
                    if username:
                        from .user_memory import UserMemory
                        topic = latest_user_message[:150].strip()
                        UserMemory(username).track("recent_conversations", topic)
                except Exception:
                    logger.debug("Conversation tracking failed", exc_info=True)

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
