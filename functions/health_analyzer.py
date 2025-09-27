import os
import openai
import json
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

# Health data categories and subcategories
HEALTH_CATEGORIES = {
    'demographics': ['BiologicalSex', 'BloodType', 'DateOfBirth', 'FitzpatrickSkinType', 'WheelchairUse'],
    'vital_signs': ['HeartRate', 'BloodPressureSystolic', 'BloodPressureDiastolic', 'Weight', 'Height', 'BMI', 'BodyFatPercentage', 'Temperature', 'RespiratoryRate', 'OxygenSaturation'],
    'activity': ['Steps', 'ActiveEnergyBurned', 'RestingEnergyBurned', 'AppleExerciseTime', 'AppleStandTime', 'DistanceWalkingRunning', 'DistanceCycling', 'DistanceSwimming', 'VO2Max'],
    'sleep': ['SleepAnalysisInterval', 'AppleSleepingWristTemperature', 'AppleSleepingBreathingDisturbances', 'SleepChanges', 'SleepApneaEvent'],
    'cardiovascular': ['HeartRate', 'HeartRateVariability', 'HeartRateRecoveryOneMinute', 'RestingHeartRate', 'HighHeartRateEvent', 'LowHeartRateEvent', 'IrregularHeartRhythmEvent', 'AtrialFibrillationBurden'],
    'symptoms': ['Headache', 'Fatigue', 'Nausea', 'Dizziness', 'Fever', 'Chills', 'Coughing', 'RunnyNose', 'SoreThroat', 'ShortnessofBreath', 'ChestTightnessorPain', 'Wheezing'],
    'medications': ['ClinicalMedication'],
    'lab_results': ['BloodGlucose', 'BloodAlcoholContent', 'ClinicalLabResult', 'FEV1', 'FVC', 'PEF'],
    'reproductive': ['MenstrualFlow', 'Pregnancy', 'PregnancyTestResult', 'ContraceptiveUse', 'OvulationTestResult', 'BasalBodyTemperature', 'Lactation'],
    'mental': ['MoodChanges', 'MindfulSession', 'AppetiteChanges', 'PhysicalEffort'],
    'environmental': ['UVExposureIndex', 'EnvironmentalAudioExposure', 'TimeInDaylight'],
    'gastrointestinal': ['Nausea', 'Vomiting', 'Diarrhea', 'Constipation', 'Bloating', 'AbdominalCramps', 'Heartburn'],
    'neurological': ['Headache', 'Dizziness', 'Fainting', 'MemoryLapse', 'LossofSmell', 'LossofTaste'],
    'dermatological': ['Acne', 'DrySkin', 'HairLoss', 'HotFlashes', 'NightSweats'],
    'respiratory': ['Coughing', 'RunnyNose', 'SoreThroat', 'ShortnessofBreath', 'ChestTightnessorPain', 'Wheezing', 'RespiratoryRate', 'FEV1', 'FVC', 'PEF'],
    'metabolic': ['BloodGlucose', 'InsulinDelivery', 'Weight', 'BMI', 'BodyFatPercentage', 'LeanBodyMass', 'WaistCircumference'],
    'mobility': ['WalkingStepLength', 'WalkingSpeed', 'WalkingAsymmetryPercentage', 'AppleWalkingSteadiness', 'WheelchairPushCount'],
    'sports': ['CyclingCadence', 'CyclingPower', 'RunningPower', 'SwimmingStrokeCount', 'RowingDistance', 'CrossCountrySkiingDistance'],
    'lifestyle': ['NumberOfAlcoholicBeverages', 'HandwashingEvent', 'ToothbrushingEvent', 'SexualActivity'],
    'clinical': ['ClinicalNote', 'ClinicalAllergy', 'ClinicalCondition', 'ClinicalProcedure', 'ClinicalImmunization', 'ClinicalVitalSign']
}

def needs_health_data(query: str) -> bool:
    """
    Determine if a query requires personal health data to answer.
    
    Args:
        query (str): The user's query
        
    Returns:
        bool: True if health data is needed, False otherwise
    """
    try:
        client = openai.OpenAI()
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a health data analyzer. Determine if a user query requires retrieving personal health data 
                    to answer accurately. Respond with EXACTLY one word: YES or NO.

YES - Query needs PHI not provided:
- Personal records: labs, vitals, medications, allergies, diagnoses, procedures, immunizations, notes, appointments
- "My" questions: trends, history, baselines, due dates, interactions, contraindications
- Data requests: "show/list/find/compare my..."

NO - Query can be answered without PHI:
- General knowledge: definitions, guidelines, education, mechanisms
- Provided values: user already includes all needed data in question
- Hypotheticals: examples not requiring actual personal data

Examples:
YES: "Am I due for Tdap?" "What were my last 3 A1c results?" "Is Paxlovid safe with my meds?" "Compare my heart rate to baseline"
NO: "What is diabetes?" "Normal A1c range?" "My BP is 130/85—what does this mean?" "Compare Ozempic vs tirzepatide" """
                },
                {
                    "role": "user",
                    "content": f"Query: {query}"
                }
            ],
            temperature=0.1,
            max_tokens=3
        )
        
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
        
    except Exception as e:
        print(f"Error in needs_health_data: {e}")
        return False

def analyze_required_categories(query: str, available_categories: Dict[str, List[str]] = None) -> Dict[str, List[str]]:
    """
    Analyze a query to determine which health categories and subcategories are needed.
    
    Args:
        query (str): The user's query
        available_categories (Dict[str, List[str]], optional): Available categories from EHR data
        
    Returns:
        Dict[str, List[str]]: Dictionary with categories as keys and subcategories as values
    """
    try:
        client = openai.OpenAI()
        
        # Use available categories if provided, otherwise use HEALTH_CATEGORIES as fallback
        if available_categories:
            categories_to_use = available_categories
            constraint_text = "You MUST ONLY select from the available categories and subcategories listed below. Do not include any categories or subcategories that are not in this list."
        else:
            categories_to_use = HEALTH_CATEGORIES
            constraint_text = "Select from the available categories and subcategories listed below."
        
        # Create a formatted list of categories and subcategories
        categories_text = ""
        for category, subcategories in categories_to_use.items():
            categories_text += f"\n{category}: {', '.join(subcategories)}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": f"""You are a health data analyzer. Given a user query, determine which health categories and subcategories are needed to answer it.

{constraint_text}

Available categories and subcategories:{categories_text}

Return a JSON object with the format:
{{
    "categories": {{
        "category_name": ["subcategory1", "subcategory2", ...],
        ...
    }}
}}

Instructions:
1. ONLY select categories and subcategories that exist in the available list above
2. Only include categories and subcategories that are relevant to answering the query
3. If no health data is needed, return: {{"categories": {{}}}}
4. Be precise - don't include categories that aren't clearly needed for the query

Examples (using only available categories):
- "What are my current medications?" → {{"categories": {{"medications": ["ClinicalMedication"]}}}}
- "How is my heart rate?" → {{"categories": {{"cardiovascular": ["HeartRate"]}}}}
- "Show me my activity data" → {{"categories": {{"activity": ["Steps", "ActiveEnergyBurned"]}}}}
- "What's my overall health status?" → {{"categories": {{"vital_signs": ["HeartRate"], "activity": ["Steps", "ActiveEnergyBurned", "AppleExerciseTime"], "cardiovascular": ["HeartRateVariability", "RestingHeartRate"], "mobility": ["WalkingSpeed", "WalkingStepLength"], "clinical": ["ClinicalCondition", "ClinicalAllergy"], "lab_results": ["ClinicalLabResult"], "medications": ["ClinicalMedication"]}}}}
- "How is my cardiovascular and mobility health?" → {{"categories": {{"cardiovascular": ["HeartRateVariability", "RestingHeartRate"], "mobility": ["WalkingSpeed", "WalkingStepLength", "AppleWalkingSteadiness", "WalkingAsymmetryPercentage"]}}}}
- "Show me my medications, lab results, and allergies" → {{"categories": {{"medications": ["ClinicalMedication"], "lab_results": ["ClinicalLabResult"], "clinical": ["ClinicalAllergy"]}}}}
- "What is diabetes?" → {{"categories": {{}}}}"""
                },
                {
                    "role": "user",
                    "content": f"Query: {query}"
                }
            ],
            temperature=0,
            max_tokens=1000
        )
        
        result = response.choices[0].message.content.strip()
        
        # Try to parse JSON response
        try:
            # Remove markdown code blocks if present
            json_result = result
            if json_result.startswith('```json'):
                json_result = json_result[7:]  # Remove ```json
            if json_result.endswith('```'):
                json_result = json_result[:-3]  # Remove ```
            
            # Replace single quotes with double quotes for proper JSON parsing
            json_result = json_result.replace("'", '"')
            parsed = json.loads(json_result.strip())
            return parsed.get("categories", {})
        except json.JSONDecodeError as e:
            # If JSON parsing fails, return empty dict and print error
            print(f"JSON parsing error: {e}")
            print(f"Raw result: {result}")
            return {}
        
    except Exception as e:
        print(f"Error in analyze_required_categories: {e}")
        return {}

def get_health_data_keys(ehr_data: Dict, required_categories: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """
    Get the actual data keys available in the EHR data for the required categories.
    
    Args:
        ehr_data (Dict): The EHR data dictionary
        required_categories (Dict[str, List[str]]): Required categories and subcategories 
    Returns:
        Dict[str, List[str]]: Available data keys for each category
    """
    available_data = {}
    
    for category, subcategories in required_categories.items():
        if category in ehr_data:
            available_subcategories = []
            for subcategory in subcategories:
                if subcategory in ehr_data[category]:
                    available_subcategories.append(subcategory)
            if available_subcategories:
                available_data[category] = available_subcategories
    
    return available_data

def format_health_categories(categories: Dict[str, List[str]]) -> str:
    """
    Format the health categories for display.
    
    Args:
        categories (Dict[str, List[str]]): Categories and subcategories 
    Returns:
        str: Formatted string for display
    """
    if not categories:
        return ""
    
    formatted = "**Health Data Categories:**\n\n"
    for category, subcategories in categories.items():
        formatted += f"**{category.replace('_', ' ').title()}:**\n"
        for subcategory in subcategories:
            formatted += f"  - {subcategory}\n"
        formatted += "\n"
    
    return formatted

def extract_categories_from_ehr(ehr_data: Dict) -> Dict[str, List[str]]:
    """
    Extract actual categories and subcategories available in the EHR data.
    
    Args:
        ehr_data (Dict): The EHR data dictionary
    Returns:
        Dict[str, List[str]]: Dictionary with actual categories as keys and subcategories as values
    """
    categories = {}
    
    summary_categories = ehr_data.get('metadata', {}).get('summary', {}).get('categories', [])
    
    for category in summary_categories:
        if category in ehr_data:
            subcategories = list(ehr_data[category].keys())
            categories[category] = subcategories
    
    return categories

def extract_raw_data_from_categories(ehr_data: Dict, categories: Dict[str, List[str]], max_items_per_subcategory: int = 100) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Extract raw data from EHR for specified categories and subcategories.
    
    Args:
        ehr_data (Dict): The EHR data dictionary
        categories (Dict[str, List[str]]): Categories and subcategories to extract
        max_items_per_subcategory (int): Maximum number of items to analyze per subcategory (default: 100)
        
    Returns:
        Dict[str, Dict[str, List[Dict]]]: Raw data organized by category and subcategory
    """
    raw_data = {}
    
    for category, subcategories in categories.items():
        if category in ehr_data:
            raw_data[category] = {}
            for subcategory in subcategories:
                if subcategory in ehr_data[category]:
                    # Get data for this subcategory
                    subcategory_data = ehr_data[category][subcategory]
                    
                    # Limit to max_items_per_subcategory for analysis if it's a list
                    if isinstance(subcategory_data, list):
                        if len(subcategory_data) > max_items_per_subcategory:
                            # Take first 100 items for analysis
                            raw_data[category][subcategory] = subcategory_data[:max_items_per_subcategory]
                        else:
                            # Take all items if less than 100
                            raw_data[category][subcategory] = subcategory_data
                    else:
                        raw_data[category][subcategory] = [subcategory_data]
                else:
                    raw_data[category][subcategory] = []
    
    return raw_data

def print_raw_health_data(raw_data: Dict[str, Dict[str, List[Dict]]]) -> str:
    """
    Format and print raw health data in a concise format.
    
    Args:
        raw_data (Dict[str, Dict[str, List[Dict]]]): Raw data to format
    Returns:
        str: Formatted string representation of the raw data
    """
    if not raw_data:
        return "No personal health data available."
    
    output = []
    
    for category, subcategories in raw_data.items():
        category_name = category.replace('_', ' ').title()
        output.append(f"\n{category_name}:")
        
        for subcategory, records in subcategories.items():
            count = len(records) if records else 0
            output.append(f"  {subcategory}: {count} records")
            
            # Show sample data from records (up to 50 per subcategory)
            if records and len(records) > 0:
                sample_records = records[:50]  # Show up to 50 records per subcategory
                
                for i, record in enumerate(sample_records, 1):
                    if isinstance(record, dict):
                        # Show all key-value pairs for each record
                        record_fields = []
                        for key, value in record.items():
                            if isinstance(value, (str, int, float, bool)):
                                record_fields.append(f"{key}={value}")
                            elif isinstance(value, list):
                                record_fields.append(f"{key}=[{len(value)} items]")
                            elif isinstance(value, dict):
                                record_fields.append(f"{key}={{dict}}")
                        if record_fields:
                            output.append(f"    Record {i}: {', '.join(record_fields)}")
                    else:
                        output.append(f"    Record {i}: {record}")
                
                # Show count of remaining records if there are more than 50
                if len(records) > 50:
                    output.append(f"    ... and {len(records) - 50} more records")
    
    return '\n'.join(output)

def analyze_health_query_with_raw_data(query: str, ehr_data: Optional[Dict] = None, show_raw_data: bool = False) -> Tuple[bool, Dict[str, List[str]], str, str]:
    """
    Complete analysis of a health query with optional raw data extraction.
    
    Args:
        query (str): The user's query
        ehr_data (Optional[Dict]): EHR data to check available keys
        show_raw_data (bool): Whether to include raw data in the response
        
    Returns:
        Tuple[bool, Dict[str, List[str]], str, str]: 
        - needs_health: Whether health data is needed
        - available_categories: Available categories in the data
        - formatted_output: Formatted string for display
        - raw_data_output: Formatted raw data (empty if show_raw_data=False)
    """
    # Import here to avoid circular imports
    from .agent import update_status
    
    # Update status before checking if health data is needed
    update_status("analyzing_health_data")
    
    # Check if health data is needed
    needs_health = needs_health_data(query)
    
    if not needs_health:
        return False, {}, "", ""
    
    # Extract available categories from EHR data if provided
    available_categories_from_ehr = None
    if ehr_data:
        available_categories_from_ehr = extract_categories_from_ehr(ehr_data)
    
    # Analyze required categories using available categories from EHR
    required_categories = analyze_required_categories(query, available_categories_from_ehr)
    
    if not required_categories:
        return True, {}, "", ""
    
    if ehr_data:
        # Update status before retrieving data from EHR
        update_status("retrieving_health_data")
        
        # Filter to only what's actually available in the EHR data
        available_categories = get_health_data_keys(ehr_data, required_categories)
        formatted_output = format_health_categories(available_categories)
        
        # Extract raw data if requested
        raw_data_output = ""
        if show_raw_data and available_categories:
            raw_data = extract_raw_data_from_categories(ehr_data, available_categories)
            raw_data_output = print_raw_health_data(raw_data)
        
        return True, available_categories, formatted_output, raw_data_output
    else:
        formatted_output = format_health_categories(required_categories)
        return True, required_categories, formatted_output, ""

def analyze_health_query(query: str, ehr_data: Optional[Dict] = None) -> Tuple[bool, Dict[str, List[str]], str]:
    """
    Complete analysis of a health query.
    
    Args:
        query (str): The user's query
        ehr_data (Optional[Dict]): EHR data to check available keys
        
    Returns:
        Tuple[bool, Dict[str, List[str]], str]: 
        - needs_health: Whether health data is needed
        - available_categories: Available categories in the data
        - formatted_output: Formatted string for display
    """
    needs_health, categories, formatted_output, _ = analyze_health_query_with_raw_data(query, ehr_data, False)
    return needs_health, categories, formatted_output