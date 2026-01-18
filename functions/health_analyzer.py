import os
import openai
import json
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

def needs_health_data(query: str) -> bool:
    """
    Determine if a query requires personal health data to answer.
    
    Args:
        query (str): The user's query
        
    Returns:
        bool: True if health data is needed, False otherwise
    """
    try:
        # Check if API key is configured
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Warning: OPENAI_API_KEY not configured")
            return False
        
        client = openai.OpenAI(api_key=api_key)
        
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

def format_patient_profile(patient_data: Dict) -> str:
    """
    Format patient profile data as a readable string.
    
    Args:
        patient_data (Dict): The patient data dictionary
    Returns:
        str: Formatted string representation of the patient profile
    """
    if not patient_data or 'patient_profile' not in patient_data:
        return "No patient data available."
    
    profile = patient_data['patient_profile']
    output = []
    
    # Demographics
    if 'demographics' in profile:
        demo = profile['demographics']
        output.append("DEMOGRAPHICS:")
        output.append(f"  Name: {demo.get('name', 'N/A')}")
        output.append(f"  Age: {demo.get('age', 'N/A')}")
        output.append(f"  Sex: {demo.get('sex', 'N/A')}")
        output.append(f"  Living situation: {demo.get('living_situation', 'N/A')}")
        output.append(f"  Baseline functional status: {demo.get('baseline_functional_status', 'N/A')}")
        output.append("")
    
    # Primary diagnosis
    if 'primary_cardiac_diagnosis' in profile:
        diagnosis = profile['primary_cardiac_diagnosis']
        output.append("PRIMARY CARDIAC DIAGNOSIS:")
        output.append(f"  Condition: {diagnosis.get('condition', 'N/A')}")
        if 'echocardiogram' in diagnosis:
            echo = diagnosis['echocardiogram']
            output.append("  Echocardiogram:")
            for key, value in echo.items():
                output.append(f"    {key}: {value}")
        output.append("")
    
    # Comorbidities
    if 'comorbidities' in profile:
        comorbidities = profile['comorbidities']
        output.append("COMORBIDITIES:")
        for category, conditions in comorbidities.items():
            output.append(f"  {category.replace('_', ' ').title()}:")
            for condition in conditions:
                output.append(f"    - {condition}")
        output.append("")
    
    # Medications
    if 'medications' in profile:
        meds = profile['medications']
        output.append("MEDICATIONS:")
        for category, med_list in meds.items():
            if category != 'supplements' and med_list:
                output.append(f"  {category.replace('_', ' ').title()}:")
                for med in med_list:
                    if isinstance(med, dict):
                        output.append(f"    - {med.get('name', 'Unknown')}: {med.get('dose', '')}")
                        output.append(f"      Indication: {med.get('indication', 'N/A')}")
                    else:
                        output.append(f"    - {med}")
        if 'supplements' in meds and meds['supplements']:
            output.append("  Supplements:")
            for supp in meds['supplements']:
                output.append(f"    - {supp}")
        output.append("")
    
    # Symptoms
    if 'symptoms' in profile:
        symptoms = profile['symptoms']
        output.append("SYMPTOMS:")
        for symptom_type, symptom_list in symptoms.items():
            output.append(f"  {symptom_type.replace('_', ' ').title()}:")
            for symptom in symptom_list:
                output.append(f"    - {symptom}")
        output.append("")
    
    # Wearable data summary
    if 'wearable_data_summary' in profile:
        wearable = profile['wearable_data_summary']
        output.append("WEARABLE DATA SUMMARY:")
        if 'ecg' in wearable and wearable['ecg']:
            output.append("  ECG:")
            for finding in wearable['ecg']:
                output.append(f"    - {finding}")
        if 'activity' in wearable:
            output.append(f"  Activity: {wearable['activity']}")
        if 'sleep' in wearable:
            output.append(f"  Sleep: {wearable['sleep']}")
        output.append("")
    
    # Recent healthcare utilization
    if 'recent_healthcare_utilization' in profile:
        recent = profile['recent_healthcare_utilization']
        output.append("RECENT HEALTHCARE UTILIZATION:")
        if 'last_hospitalization' in recent:
            hosp = recent['last_hospitalization']
            output.append(f"  Last hospitalization ({hosp.get('time_ago', 'N/A')}):")
            output.append(f"    Reason: {hosp.get('reason', 'N/A')}")
            output.append(f"    Length of stay: {hosp.get('length_of_stay_days', 'N/A')} days")
            if 'treatments' in hosp:
                output.append("    Treatments:")
                for treatment in hosp['treatments']:
                    output.append(f"      - {treatment}")
        if 'last_cardiology_clinic_visit' in recent:
            visit = recent['last_cardiology_clinic_visit']
            output.append(f"  Last cardiology visit ({visit.get('time_ago', 'N/A')}):")
            output.append(f"    Status: {visit.get('status_at_visit', 'N/A')}")
        output.append("")
    
    return '\n'.join(output)

def analyze_health_query_with_raw_data(query: str, patient_data: Optional[Dict] = None, show_raw_data: bool = False, mobile_data: Optional[Dict] = None) -> Tuple[bool, Dict, str, str]:
    """
    Simplified analysis of a health query with patient profile data and mobile health data.
    
    Args:
        query (str): The user's query
        patient_data (Optional[Dict]): Patient data to include
        show_raw_data (bool): Whether to include formatted patient data in the response
        mobile_data (Optional[Dict]): Mobile health data to check for relevance
        
    Returns:
        Tuple[bool, Dict, str, str]: 
        - needs_health: Whether health data is needed
        - patient_profile: Patient profile dict (empty if not available)
        - formatted_output: Brief description
        - raw_data_output: Formatted patient profile and/or mobile data (empty if show_raw_data=False or no data)
    """
    # Import here to avoid circular imports
    from .agent import update_status
    from .mobile_data_retriever import retrieve_relevant_mobile_data
    
    # Check if health data is needed first
    needs_health = needs_health_data(query)
    
    # Also check if mobile data is needed
    needs_mobile, mobile_retrieved, mobile_formatted = retrieve_relevant_mobile_data(query, mobile_data or {})
    
    # If neither patient nor mobile data is needed, return early
    if not needs_health and not needs_mobile:
        return False, {}, "", ""
    
    # Update status
    update_status("retrieving_health_data")
    
    formatted_output_parts = []
    raw_data_output_parts = []
    
    # Process patient data if needed
    patient_profile = {}
    if needs_health:
        if not patient_data:
            formatted_output_parts.append("Patient data requested but not available")
        else:
            patient_profile = patient_data.get('patient_profile', {})
            
            if not patient_profile:
                formatted_output_parts.append("Patient profile not found in data")
            else:
                # Simple formatted output
                name = patient_profile.get('demographics', {}).get('name', 'Patient')
                formatted_output_parts.append(f"Patient profile available for {name}")
                
                # Format full patient data if requested
                if show_raw_data:
                    update_status("analyzing_health_data")
                    raw_data_output_parts.append(format_patient_profile(patient_data))
    
    # Process mobile data if needed
    if needs_mobile:
        if mobile_retrieved:
            formatted_output_parts.append("Mobile health data retrieved")
            if show_raw_data and mobile_formatted:
                raw_data_output_parts.append("\n=== MOBILE HEALTH DATA ===\n" + mobile_formatted)
        else:
            formatted_output_parts.append("Mobile health data requested but not available")
    
    # Combine outputs
    formatted_output = " | ".join(formatted_output_parts) if formatted_output_parts else ""
    raw_data_output = "\n\n".join(raw_data_output_parts) if raw_data_output_parts else ""
    
    return (needs_health or needs_mobile), patient_profile, formatted_output, raw_data_output

def analyze_health_query(query: str, patient_data: Optional[Dict] = None) -> Tuple[bool, Dict, str]:
    """
    Simplified analysis of a health query.
    
    Args:
        query (str): The user's query
        patient_data (Optional[Dict]): Patient data to check
        
    Returns:
        Tuple[bool, Dict, str]: 
        - needs_health: Whether health data is needed
        - patient_profile: Patient profile dict
        - formatted_output: Formatted string for display
    """
    needs_health, profile, formatted_output, _ = analyze_health_query_with_raw_data(query, patient_data, False)
    return needs_health, profile, formatted_output