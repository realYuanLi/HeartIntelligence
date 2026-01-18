"""
Mobile Health Data Processor

Processes raw HealthKit data from JSON-Lines files into structured, aggregated format.
Focus on heart metrics (heart rate, HRV, blood pressure) with support for other categories.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import statistics


def load_jsonl_file(filepath: Path) -> List[Dict]:
    """Load a JSON-Lines file (one JSON object per line)."""
    data = []
    if not filepath.exists() or filepath.stat().st_size == 0:
        return data
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"Error loading {filepath.name}: {e}")
    
    return data


def parse_iso_date(date_str: str, date_offset_days: int = 0) -> Optional[datetime]:
    """
    Parse ISO date string to datetime object with optional offset.
    
    Args:
        date_str: ISO format date string
        date_offset_days: Number of days to add to the parsed date (for shifting data forward)
    """
    if not date_str:
        return None
    
    try:
        # Handle formats like "2025-08-24T23:45:07-04:00"
        if 'T' in date_str:
            # Remove timezone suffix for parsing
            if date_str.endswith('Z'):
                date_str = date_str[:-1]
            elif '+' in date_str[-6:] or '-' in date_str[-6:]:
                date_str = date_str[:-6]
            
            dt = datetime.fromisoformat(date_str)
        else:
            dt = datetime.fromisoformat(date_str)
        
        # Apply date offset if specified
        if date_offset_days != 0:
            dt = dt + timedelta(days=date_offset_days)
        
        return dt
    except Exception as e:
        print(f"Error parsing date {date_str}: {e}")
        return None


def get_date_key(dt: datetime) -> str:
    """Convert datetime to date key (YYYY-MM-DD)."""
    return dt.strftime("%Y-%m-%d")


def load_raw_mobile_data(directory_path: Path) -> Dict[str, List[Dict]]:
    """
    Load all raw mobile data files and organize by category.
    
    Returns:
        Dict with keys like 'heart_rate', 'blood_pressure_systolic', etc.
    """
    if not directory_path.exists():
        print(f"Directory not found: {directory_path}")
        return {}
    
    raw_data = {}
    
    # Define file patterns and their categories
    file_categories = {
        'heart_rate': 'HealthKitV2Samples_HeartRate_',
        'hrv': 'HealthKitV2Samples_HeartRateVariability_',
        'blood_pressure_systolic': 'HealthKitV2Samples_BloodPressureSystolic_',
        'blood_pressure_diastolic': 'HealthKitV2Samples_BloodPressureDiastolic_',
        'steps': 'HealthKitV2Samples_Steps_',
        'activity_summary': 'HealthKitV2ActivitySummaries_',
        'exercise_time': 'HealthKitV2Samples_AppleExerciseTime_',
        'active_energy': 'HealthKitV2Samples_ActiveEnergyBurned_',
        'daily_steps': 'HealthKitV2Statistics_DailySteps_',
        'hourly_hr_max': 'HealthKitV2Statistics_HourlyMaximumHeartRate_',
        'hourly_hr_min': 'HealthKitV2Statistics_HourlyMinimumHeartRate_',
    }
    
    # Load files for each category
    for category, file_pattern in file_categories.items():
        files = list(directory_path.glob(f"{file_pattern}*.json"))
        category_data = []
        
        for file in files:
            # Skip deleted files
            if '_Deleted_' in file.name:
                continue
            
            file_data = load_jsonl_file(file)
            category_data.extend(file_data)
        
        if category_data:
            raw_data[category] = category_data
            print(f"Loaded {len(category_data)} records for {category}")
    
    return raw_data


def process_heart_rate_data(raw_data: List[Dict], date_offset_days: int = 0) -> Dict:
    """
    Process heart rate samples into daily statistics and trends.
    
    Args:
        raw_data: List of heart rate records
        date_offset_days: Number of days to offset dates (for updating to recent dates)
    
    Returns:
        Dict with daily_stats, recent_samples, and trends
    """
    if not raw_data:
        return {'daily_stats': [], 'recent_samples': [], 'trends': {}}
    
    # Group by date
    daily_values = defaultdict(list)
    all_samples = []
    
    for record in raw_data:
        date_str = record.get('Date') or record.get('StartDate')
        if not date_str:
            continue
        
        dt = parse_iso_date(date_str, date_offset_days)
        if not dt:
            continue
        
        date_key = get_date_key(dt)
        
        try:
            value = float(record.get('Value', 0))
            if value > 0:  # Filter out invalid values
                daily_values[date_key].append(value)
                all_samples.append({
                    'date': dt.isoformat(),  # Use shifted date
                    'value': value,
                    'units': record.get('Units', 'count/min')
                })
        except (ValueError, TypeError):
            continue
    
    # Calculate daily statistics
    daily_stats = []
    for date_key in sorted(daily_values.keys()):
        values = daily_values[date_key]
        daily_stats.append({
            'date': date_key,
            'avg': round(statistics.mean(values), 1),
            'min': round(min(values), 1),
            'max': round(max(values), 1),
            'count': len(values)
        })
    
    # Calculate trends
    trends = calculate_heart_rate_trends(daily_stats)
    
    # Keep only recent samples (last 50)
    recent_samples = sorted(all_samples, key=lambda x: x['date'], reverse=True)[:50]
    
    return {
        'daily_stats': daily_stats,
        'recent_samples': recent_samples,
        'trends': trends
    }


def process_blood_pressure_data(systolic_data: List[Dict], diastolic_data: List[Dict], date_offset_days: int = 0) -> Dict:
    """
    Process blood pressure data (systolic and diastolic).
    
    Args:
        systolic_data: List of systolic BP records
        diastolic_data: List of diastolic BP records
        date_offset_days: Number of days to offset dates
    
    Returns:
        Dict with readings and trends
    """
    if not systolic_data and not diastolic_data:
        return {'readings': [], 'trends': {}}
    
    # Combine systolic and diastolic by matching timestamps
    readings_dict = {}
    
    # Process systolic
    for record in systolic_data:
        date_str = record.get('Date') or record.get('StartDate')
        if not date_str:
            continue
        
        dt = parse_iso_date(date_str, date_offset_days)
        if not dt:
            continue
        
        shifted_date = dt.isoformat()
        
        try:
            value = float(record.get('Value', 0))
            if value > 0:
                readings_dict[shifted_date] = readings_dict.get(shifted_date, {})
                readings_dict[shifted_date]['systolic'] = value
                readings_dict[shifted_date]['date'] = shifted_date
        except (ValueError, TypeError):
            continue
    
    # Process diastolic
    for record in diastolic_data:
        date_str = record.get('Date') or record.get('StartDate')
        if not date_str:
            continue
        
        dt = parse_iso_date(date_str, date_offset_days)
        if not dt:
            continue
        
        shifted_date = dt.isoformat()
        
        try:
            value = float(record.get('Value', 0))
            if value > 0:
                readings_dict[shifted_date] = readings_dict.get(shifted_date, {})
                readings_dict[shifted_date]['diastolic'] = value
                readings_dict[shifted_date]['date'] = shifted_date
        except (ValueError, TypeError):
            continue
    
    # Convert to list and sort
    readings = [r for r in readings_dict.values() if 'systolic' in r or 'diastolic' in r]
    readings.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate trends
    trends = calculate_bp_trends(readings)
    
    return {
        'readings': readings[:100],  # Keep last 100 readings
        'trends': trends
    }


def process_hrv_data(raw_data: List[Dict], date_offset_days: int = 0) -> Dict:
    """
    Process heart rate variability data.
    
    Args:
        raw_data: List of HRV records
        date_offset_days: Number of days to offset dates
    
    Returns:
        Dict with daily averages and trends
    """
    if not raw_data:
        return {'daily_averages': [], 'trends': {}}
    
    # Group by date
    daily_values = defaultdict(list)
    
    for record in raw_data:
        date_str = record.get('Date') or record.get('StartDate')
        if not date_str:
            continue
        
        dt = parse_iso_date(date_str, date_offset_days)
        if not dt:
            continue
        
        date_key = get_date_key(dt)
        
        try:
            value = float(record.get('Value', 0))
            if value > 0:  # Filter out invalid values
                daily_values[date_key].append(value)
        except (ValueError, TypeError):
            continue
    
    # Calculate daily averages
    daily_averages = []
    for date_key in sorted(daily_values.keys()):
        values = daily_values[date_key]
        daily_averages.append({
            'date': date_key,
            'avg': round(statistics.mean(values), 1),
            'count': len(values)
        })
    
    # Calculate trends
    trends = calculate_hrv_trends(daily_averages)
    
    return {
        'daily_averages': daily_averages,
        'trends': trends
    }


def calculate_daily_aggregates(samples: List[Dict], value_key: str = 'Value', date_offset_days: int = 0) -> List[Dict]:
    """
    Generic function to calculate daily aggregates from samples.
    
    Args:
        samples: List of sample records
        value_key: Key to extract value from (default 'Value')
        date_offset_days: Number of days to offset dates
    
    Returns:
        List of daily aggregates with sum, avg, min, max
    """
    if not samples:
        return []
    
    daily_values = defaultdict(list)
    
    for record in samples:
        date_str = record.get('Date') or record.get('StartDate')
        if not date_str:
            continue
        
        dt = parse_iso_date(date_str, date_offset_days)
        if not dt:
            continue
        
        date_key = get_date_key(dt)
        
        try:
            value = float(record.get(value_key, 0))
            if value >= 0:  # Allow zero for some metrics
                daily_values[date_key].append(value)
        except (ValueError, TypeError):
            continue
    
    # Calculate daily statistics
    daily_stats = []
    for date_key in sorted(daily_values.keys()):
        values = daily_values[date_key]
        daily_stats.append({
            'date': date_key,
            'sum': round(sum(values), 1),
            'avg': round(statistics.mean(values), 1),
            'min': round(min(values), 1),
            'max': round(max(values), 1),
            'count': len(values)
        })
    
    return daily_stats


def calculate_heart_rate_trends(daily_stats: List[Dict]) -> Dict:
    """Calculate trends for heart rate data."""
    if len(daily_stats) < 2:
        return {'recent_avg': None, 'trend': 'insufficient_data'}
    
    # Get recent average (last 7 days)
    recent_days = daily_stats[-7:]
    recent_avg = statistics.mean([d['avg'] for d in recent_days])
    
    # Calculate trend (comparing first half vs second half of recent period)
    if len(daily_stats) >= 14:
        first_half = daily_stats[-14:-7]
        second_half = daily_stats[-7:]
        first_avg = statistics.mean([d['avg'] for d in first_half])
        second_avg = statistics.mean([d['avg'] for d in second_half])
        
        diff = second_avg - first_avg
        if abs(diff) < 2:
            trend = 'stable'
        elif diff > 0:
            trend = 'increasing'
        else:
            trend = 'decreasing'
    else:
        trend = 'stable'
    
    return {
        'recent_avg': round(recent_avg, 1),
        'trend': trend,
        'min_recorded': min([d['min'] for d in daily_stats]),
        'max_recorded': max([d['max'] for d in daily_stats])
    }


def calculate_bp_trends(readings: List[Dict]) -> Dict:
    """Calculate trends for blood pressure data."""
    if len(readings) < 2:
        return {'recent_avg_systolic': None, 'recent_avg_diastolic': None, 'trend': 'insufficient_data'}
    
    # Get recent averages
    systolic_values = [r['systolic'] for r in readings if 'systolic' in r]
    diastolic_values = [r['diastolic'] for r in readings if 'diastolic' in r]
    
    trends = {}
    
    if systolic_values:
        recent_systolic = systolic_values[:7] if len(systolic_values) >= 7 else systolic_values
        trends['recent_avg_systolic'] = round(statistics.mean(recent_systolic), 1)
        
        if len(systolic_values) >= 14:
            older_systolic = systolic_values[7:14]
            diff = trends['recent_avg_systolic'] - statistics.mean(older_systolic)
            if abs(diff) < 5:
                trends['systolic_trend'] = 'stable'
            elif diff > 0:
                trends['systolic_trend'] = 'increasing'
            else:
                trends['systolic_trend'] = 'decreasing'
        else:
            trends['systolic_trend'] = 'stable'
    
    if diastolic_values:
        recent_diastolic = diastolic_values[:7] if len(diastolic_values) >= 7 else diastolic_values
        trends['recent_avg_diastolic'] = round(statistics.mean(recent_diastolic), 1)
        
        if len(diastolic_values) >= 14:
            older_diastolic = diastolic_values[7:14]
            diff = trends['recent_avg_diastolic'] - statistics.mean(older_diastolic)
            if abs(diff) < 3:
                trends['diastolic_trend'] = 'stable'
            elif diff > 0:
                trends['diastolic_trend'] = 'increasing'
            else:
                trends['diastolic_trend'] = 'decreasing'
        else:
            trends['diastolic_trend'] = 'stable'
    
    return trends


def calculate_hrv_trends(daily_averages: List[Dict]) -> Dict:
    """Calculate trends for HRV data."""
    if len(daily_averages) < 2:
        return {'recent_avg': None, 'trend': 'insufficient_data'}
    
    # Get recent average (last 7 days)
    recent_days = daily_averages[-7:]
    recent_avg = statistics.mean([d['avg'] for d in recent_days])
    
    # Calculate trend
    if len(daily_averages) >= 14:
        first_half = daily_averages[-14:-7]
        second_half = daily_averages[-7:]
        first_avg = statistics.mean([d['avg'] for d in first_half])
        second_avg = statistics.mean([d['avg'] for d in second_half])
        
        diff = second_avg - first_avg
        if abs(diff) < 5:
            trend = 'stable'
        elif diff > 0:
            trend = 'improving'  # Higher HRV is generally better
        else:
            trend = 'declining'
    else:
        trend = 'stable'
    
    return {
        'recent_avg': round(recent_avg, 1),
        'trend': trend
    }


def process_all_mobile_data(directory_path: Path, date_offset_days: int = 0) -> Dict:
    """
    Main function to process all mobile health data.
    
    Args:
        directory_path: Path to raw_mobile directory
        date_offset_days: Number of days to offset all dates (for updating to recent dates)
        
    Returns:
        Processed data dictionary
    """
    print("Loading raw mobile data...")
    raw_data = load_raw_mobile_data(directory_path)
    
    if not raw_data:
        print("No data loaded.")
        return {}
    
    if date_offset_days != 0:
        print(f"Applying date offset: +{date_offset_days} days to shift data to recent dates")
    
    print("\nProcessing heart rate data...")
    heart_rate = process_heart_rate_data(raw_data.get('heart_rate', []), date_offset_days)
    
    print("Processing blood pressure data...")
    blood_pressure = process_blood_pressure_data(
        raw_data.get('blood_pressure_systolic', []),
        raw_data.get('blood_pressure_diastolic', []),
        date_offset_days
    )
    
    print("Processing HRV data...")
    hrv = process_hrv_data(raw_data.get('hrv', []), date_offset_days)
    
    print("Processing activity data...")
    steps_daily = calculate_daily_aggregates(raw_data.get('daily_steps', []), 'Value', date_offset_days)
    
    # Determine date range
    all_dates = []
    if heart_rate['daily_stats']:
        all_dates.extend([d['date'] for d in heart_rate['daily_stats']])
    if steps_daily:
        all_dates.extend([d['date'] for d in steps_daily])
    
    date_range = {}
    if all_dates:
        date_range = {
            'start': min(all_dates),
            'end': max(all_dates)
        }
    
    # Build final structure
    processed_data = {
        'last_updated': datetime.now().isoformat(),
        'date_range': date_range,
        'heart_data': {
            'heart_rate': heart_rate,
            'blood_pressure': blood_pressure,
            'hrv': hrv
        },
        'activity_data': {
            'daily_steps': steps_daily
        },
        'metadata': {
            'total_days': len(set(all_dates)) if all_dates else 0,
            'categories_processed': list(raw_data.keys())
        }
    }
    
    print("\nProcessing complete!")
    print(f"Date range: {date_range.get('start', 'N/A')} to {date_range.get('end', 'N/A')}")
    print(f"Total days: {processed_data['metadata']['total_days']}")
    
    return processed_data


def save_processed_data(data: Dict, output_path: Path):
    """Save processed data to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved processed data to: {output_path}")
