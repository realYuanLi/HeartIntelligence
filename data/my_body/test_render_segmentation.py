#!/usr/bin/env python3
"""
Independent test script to render the segmentation file.
This script loads and visualizes the s0000_seg.nii.gz file.
"""

import nibabel as nib
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

# Path to the segmentation file
SEG_FILE = Path(__file__).parent / "seg_map_clean" / "s1038_seg.nii.gz"

def main():
    print(f"Loading segmentation file: {SEG_FILE}")
    
    # Check if file exists
    if not SEG_FILE.exists():
        print(f"ERROR: File not found at {SEG_FILE}")
        return
    
    # Load the segmentation file
    try:
        seg_img = nib.load(str(SEG_FILE))
        seg_data = seg_img.get_fdata()
        
        print(f"\n=== Segmentation File Info ===")
        print(f"Shape: {seg_data.shape}")
        print(f"Data type: {seg_data.dtype}")
        print(f"Min value: {seg_data.min()}")
        print(f"Max value: {seg_data.max()}")
        print(f"Unique labels: {np.unique(seg_data)}")
        print(f"Affine shape: {seg_img.affine.shape}")
        print(f"Header: {seg_img.header}")
        
        # Render middle slices from all three axes
        render_slices(seg_data)
        
    except Exception as e:
        print(f"ERROR loading file: {e}")
        import traceback
        traceback.print_exc()

def render_slices(seg_data):
    """Render middle slices from all three axes"""
    print(f"\n=== Rendering Slices ===")
    
    # Get middle slices
    mid_x = seg_data.shape[0] // 2
    mid_y = seg_data.shape[1] // 2
    mid_z = seg_data.shape[2] // 2
    
    # Create figure with 3 subplots
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    # Sagittal view (YZ plane, fixed X)
    sagittal = seg_data[mid_x, :, :]
    axes[0].imshow(sagittal.T, cmap='nipy_spectral', origin='lower')
    axes[0].set_title(f'Sagittal View (X={mid_x})')
    axes[0].set_xlabel('Y axis')
    axes[0].set_ylabel('Z axis')
    axes[0].axis('off')
    
    # Coronal view (XZ plane, fixed Y)
    coronal = seg_data[:, mid_y, :]
    axes[1].imshow(coronal.T, cmap='nipy_spectral', origin='lower')
    axes[1].set_title(f'Coronal View (Y={mid_y})')
    axes[1].set_xlabel('X axis')
    axes[1].set_ylabel('Z axis')
    axes[1].axis('off')
    
    # Axial view (XY plane, fixed Z)
    axial = seg_data[:, :, mid_z]
    axes[2].imshow(axial.T, cmap='nipy_spectral', origin='lower')
    axes[2].set_title(f'Axial View (Z={mid_z})')
    axes[2].set_xlabel('X axis')
    axes[2].set_ylabel('Y axis')
    axes[2].axis('off')
    
    plt.tight_layout()
    
    # Save the figure
    output_file = Path(__file__).parent / "test_segmentation_render.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved visualization to: {output_file}")
    
    # Show the plot
    plt.show()
    print("Displaying visualization...")

if __name__ == "__main__":
    main()

