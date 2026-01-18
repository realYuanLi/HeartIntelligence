#!/usr/bin/env python3
"""
Process Mobile Health Data Script

Processes raw HealthKit data and generates processed_mobile_data.json
Usage: python process_mobile_data.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from functions.mobile_data_processor import process_all_mobile_data, save_processed_data


def main():
    """Main processing function."""
    print("=" * 60)
    print("Mobile Health Data Processor")
    print("=" * 60)
    print()
    
    # Define paths
    raw_data_dir = project_root / "data" / "raw_mobile"
    output_file = project_root / "data" / "processed_mobile_data.json"
    
    # Check if raw data directory exists
    if not raw_data_dir.exists():
        print(f"ERROR: Raw data directory not found: {raw_data_dir}")
        sys.exit(1)
    
    # Calculate date offset to shift data to recent dates (January 2026)
    # Original data ends: 2025-09-15
    # Target end date: 2026-01-16
    # Days between: 123 days
    date_offset_days = 123
    
    print(f"Shifting dates by {date_offset_days} days to update to recent dates (January 2026)")
    print()
    
    # Process the data
    try:
        processed_data = process_all_mobile_data(raw_data_dir, date_offset_days)
        
        if not processed_data:
            print("ERROR: No data was processed.")
            sys.exit(1)
        
        # Save to file
        save_processed_data(processed_data, output_file)
        
        print()
        print("=" * 60)
        print("SUCCESS: Processing complete!")
        print("=" * 60)
        
        # Print summary
        print("\nSummary:")
        heart_data = processed_data.get('heart_data', {})
        
        if 'heart_rate' in heart_data:
            hr_stats = heart_data['heart_rate'].get('daily_stats', [])
            print(f"  Heart Rate: {len(hr_stats)} days of data")
            if heart_data['heart_rate'].get('trends', {}).get('recent_avg'):
                print(f"    Recent avg: {heart_data['heart_rate']['trends']['recent_avg']} bpm")
        
        if 'blood_pressure' in heart_data:
            bp_readings = heart_data['blood_pressure'].get('readings', [])
            print(f"  Blood Pressure: {len(bp_readings)} readings")
            trends = heart_data['blood_pressure'].get('trends', {})
            if trends.get('recent_avg_systolic'):
                print(f"    Recent avg: {trends['recent_avg_systolic']}/{trends.get('recent_avg_diastolic', 'N/A')} mmHg")
        
        if 'hrv' in heart_data:
            hrv_data = heart_data['hrv'].get('daily_averages', [])
            print(f"  HRV: {len(hrv_data)} days of data")
            if heart_data['hrv'].get('trends', {}).get('recent_avg'):
                print(f"    Recent avg: {heart_data['hrv']['trends']['recent_avg']} ms")
        
        activity_data = processed_data.get('activity_data', {})
        if 'daily_steps' in activity_data:
            steps = activity_data['daily_steps']
            print(f"  Steps: {len(steps)} days of data")
        
        print(f"\nOutput file: {output_file}")
        
    except Exception as e:
        print(f"\nERROR: Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
