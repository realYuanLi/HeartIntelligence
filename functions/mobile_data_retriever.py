"""
Mobile Data Retriever

Retrieves relevant mobile health data based on user queries using keyword matching.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import re


# Keyword categories for different data types
HEART_RATE_KEYWORDS = [
    'heart rate', 'heartrate', 'hr', 'bpm', 'pulse', 'heartbeat', 'beats per minute',
    'resting heart rate', 'heart rhythm', 'cardiac rate'
]

BLOOD_PRESSURE_KEYWORDS = [
    'blood pressure', 'bp', 'systolic', 'diastolic', 'hypertension', 'hypotension',
    'pressure reading', 'mmhg'
]

HRV_KEYWORDS = [
    'heart rate variability', 'hrv', 'variability', 'heart variability',
    'cardiac variability'
]

ACTIVITY_KEYWORDS = [
    'steps', 'walking', 'activity', 'exercise', 'movement', 'active',
    'physical activity', 'daily steps', 'step count'
]

TIME_KEYWORDS = {
    'today': 0,
    'yesterday': 1,
    'this week': 7,
    'last week': 14,
    'past week': 7,
    'recent': 7,
    'last month': 30,
    'this month': 30,
}

TREND_KEYWORDS = [
    'trend', 'trending', 'change', 'changes', 'changing', 'improve', 'improving',
    'improvement', 'worse', 'worsening', 'better', 'declining', 'increasing',
    'decreasing', 'stable', 'pattern', 'patterns'
]


def contains_keywords(query: str, keywords: List[str]) -> bool:
    """Check if query contains any of the keywords."""
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in keywords)


def extract_time_range(query: str) -> Optional[int]:
    """
    Extract time range from query in days.
    Returns number of days to look back, or None if not specified.
    """
    query_lower = query.lower()
    
    for time_phrase, days in TIME_KEYWORDS.items():
        if time_phrase in query_lower:
            return days
    
    # Check for specific day numbers
    day_match = re.search(r'last (\d+) days?', query_lower)
    if day_match:
        return int(day_match.group(1))
    
    week_match = re.search(r'last (\d+) weeks?', query_lower)
    if week_match:
        return int(week_match.group(1)) * 7
    
    return None


def filter_by_date_range(data_list: List[Dict], days_back: int) -> List[Dict]:
    """
    Filter data list by date range.
    
    Args:
        data_list: List of data items with 'date' field
        days_back: Number of days to look back from now
        
    Returns:
        Filtered list of data items
    """
    if not data_list or days_back is None:
        return data_list
    
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    filtered = [item for item in data_list if item.get('date', '') >= cutoff_date]
    return filtered


def needs_mobile_data(query: str) -> bool:
    """
    Determine if a query requires mobile health data.
    
    Args:
        query: User query string
        
    Returns:
        True if mobile data is needed, False otherwise
    """
    all_keywords = (
        HEART_RATE_KEYWORDS + 
        BLOOD_PRESSURE_KEYWORDS + 
        HRV_KEYWORDS + 
        ACTIVITY_KEYWORDS
    )
    
    return contains_keywords(query, all_keywords)


def retrieve_relevant_mobile_data(query: str, processed_data: Dict) -> Tuple[bool, Dict, str]:
    """
    Retrieve relevant mobile health data based on user query.
    
    Args:
        query: User query string
        processed_data: Processed mobile health data dictionary
        
    Returns:
        Tuple of (needs_data, retrieved_data, formatted_string)
        - needs_data: Whether mobile data is relevant to the query
        - retrieved_data: Dictionary of relevant data
        - formatted_string: Human-readable formatted data for AI context
    """
    if not processed_data:
        return False, {}, ""
    
    # Check if mobile data is needed
    if not needs_mobile_data(query):
        return False, {}, ""
    
    # Extract time range
    days_back = extract_time_range(query)
    if days_back is None:
        days_back = 7  # Default to last 7 days
    
    # Check for trend analysis request
    needs_trends = contains_keywords(query, TREND_KEYWORDS)
    
    retrieved_data = {}
    formatted_parts = []
    
    heart_data = processed_data.get('heart_data', {})
    activity_data = processed_data.get('activity_data', {})
    
    # Heart Rate Data
    if contains_keywords(query, HEART_RATE_KEYWORDS):
        hr_info = heart_data.get('heart_rate', {})
        if hr_info:
            daily_stats = filter_by_date_range(hr_info.get('daily_stats', []), days_back)
            
            retrieved_data['heart_rate'] = {
                'daily_stats': daily_stats,
                'trends': hr_info.get('trends', {}) if needs_trends else {}
            }
            
            formatted_parts.append(format_heart_rate_data(daily_stats, hr_info.get('trends', {}), needs_trends))
    
    # Blood Pressure Data
    if contains_keywords(query, BLOOD_PRESSURE_KEYWORDS):
        bp_info = heart_data.get('blood_pressure', {})
        if bp_info:
            readings = bp_info.get('readings', [])
            # Filter by days back (readings are already sorted by date, most recent first)
            filtered_readings = readings[:days_back] if days_back else readings[:14]
            
            retrieved_data['blood_pressure'] = {
                'readings': filtered_readings,
                'trends': bp_info.get('trends', {}) if needs_trends else {}
            }
            
            formatted_parts.append(format_blood_pressure_data(filtered_readings, bp_info.get('trends', {}), needs_trends))
    
    # HRV Data
    if contains_keywords(query, HRV_KEYWORDS):
        hrv_info = heart_data.get('hrv', {})
        if hrv_info:
            daily_avgs = filter_by_date_range(hrv_info.get('daily_averages', []), days_back)
            
            retrieved_data['hrv'] = {
                'daily_averages': daily_avgs,
                'trends': hrv_info.get('trends', {}) if needs_trends else {}
            }
            
            formatted_parts.append(format_hrv_data(daily_avgs, hrv_info.get('trends', {}), needs_trends))
    
    # Activity Data
    if contains_keywords(query, ACTIVITY_KEYWORDS):
        steps_data = activity_data.get('daily_steps', [])
        if steps_data:
            filtered_steps = filter_by_date_range(steps_data, days_back)
            
            retrieved_data['activity'] = {
                'daily_steps': filtered_steps
            }
            
            formatted_parts.append(format_activity_data(filtered_steps))
    
    if not formatted_parts:
        return False, {}, ""
    
    # Combine formatted parts
    formatted_output = "\n\n".join(formatted_parts)
    
    return True, retrieved_data, formatted_output


def format_heart_rate_data(daily_stats: List[Dict], trends: Dict, include_trends: bool) -> str:
    """Format heart rate data for AI context."""
    if not daily_stats:
        return "HEART RATE DATA:\n  No data available for the requested period."
    
    output = ["HEART RATE DATA:"]
    
    # Recent summary
    recent_values = [d['avg'] for d in daily_stats[-7:]]
    if recent_values:
        avg = sum(recent_values) / len(recent_values)
        output.append(f"  Recent 7-day average: {avg:.1f} bpm")
    
    # Trends if requested
    if include_trends and trends:
        if trends.get('recent_avg'):
            output.append(f"  Overall average: {trends['recent_avg']} bpm")
        if trends.get('trend'):
            output.append(f"  Trend: {trends['trend']}")
        if trends.get('min_recorded') and trends.get('max_recorded'):
            output.append(f"  Range: {trends['min_recorded']}-{trends['max_recorded']} bpm")
    
    # Daily breakdown (show last 7 days or less)
    output.append("\n  Daily breakdown:")
    for stat in daily_stats[-7:]:
        output.append(f"    {stat['date']}: avg {stat['avg']} bpm (range: {stat['min']}-{stat['max']})")
    
    return "\n".join(output)


def format_blood_pressure_data(readings: List[Dict], trends: Dict, include_trends: bool) -> str:
    """Format blood pressure data for AI context."""
    if not readings:
        return "BLOOD PRESSURE DATA:\n  No data available for the requested period."
    
    output = ["BLOOD PRESSURE DATA:"]
    
    # Recent averages
    systolic_values = [r['systolic'] for r in readings if 'systolic' in r]
    diastolic_values = [r['diastolic'] for r in readings if 'diastolic' in r]
    
    if systolic_values:
        avg_sys = sum(systolic_values) / len(systolic_values)
        output.append(f"  Average systolic: {avg_sys:.1f} mmHg")
    if diastolic_values:
        avg_dia = sum(diastolic_values) / len(diastolic_values)
        output.append(f"  Average diastolic: {avg_dia:.1f} mmHg")
    
    # Trends if requested
    if include_trends and trends:
        if trends.get('systolic_trend'):
            output.append(f"  Systolic trend: {trends['systolic_trend']}")
        if trends.get('diastolic_trend'):
            output.append(f"  Diastolic trend: {trends['diastolic_trend']}")
    
    # Recent readings (show last 5)
    output.append("\n  Recent readings:")
    for reading in readings[:5]:
        sys = reading.get('systolic', 'N/A')
        dia = reading.get('diastolic', 'N/A')
        date = reading.get('date', 'Unknown')[:10]  # Just the date part
        output.append(f"    {date}: {sys}/{dia} mmHg")
    
    return "\n".join(output)


def format_hrv_data(daily_averages: List[Dict], trends: Dict, include_trends: bool) -> str:
    """Format HRV data for AI context."""
    if not daily_averages:
        return "HRV DATA:\n  No data available for the requested period."
    
    output = ["HEART RATE VARIABILITY (HRV) DATA:"]
    
    # Recent summary
    recent_values = [d['avg'] for d in daily_averages[-7:]]
    if recent_values:
        avg = sum(recent_values) / len(recent_values)
        output.append(f"  Recent 7-day average: {avg:.1f} ms")
    
    # Trends if requested
    if include_trends and trends:
        if trends.get('recent_avg'):
            output.append(f"  Overall average: {trends['recent_avg']} ms")
        if trends.get('trend'):
            output.append(f"  Trend: {trends['trend']}")
            output.append("  Note: Higher HRV generally indicates better cardiovascular fitness and recovery")
    
    # Daily breakdown
    output.append("\n  Daily breakdown:")
    for stat in daily_averages[-7:]:
        output.append(f"    {stat['date']}: {stat['avg']} ms")
    
    return "\n".join(output)


def format_activity_data(daily_steps: List[Dict]) -> str:
    """Format activity data for AI context."""
    if not daily_steps:
        return "ACTIVITY DATA:\n  No data available for the requested period."
    
    output = ["ACTIVITY DATA (Daily Steps):"]
    
    # Summary
    step_counts = [d['sum'] for d in daily_steps]
    if step_counts:
        avg_steps = sum(step_counts) / len(step_counts)
        output.append(f"  Average daily steps: {avg_steps:.0f}")
        output.append(f"  Highest: {max(step_counts):.0f} steps")
        output.append(f"  Lowest: {min(step_counts):.0f} steps")
    
    # Daily breakdown (last 7 days)
    output.append("\n  Daily breakdown:")
    for stat in daily_steps[-7:]:
        output.append(f"    {stat['date']}: {stat['sum']:.0f} steps")
    
    return "\n".join(output)
