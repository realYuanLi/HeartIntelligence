"""
Transform exercise images into illustrated fitness-app style using Google Nano Banana
(Gemini image generation). Preserves exact pose/motion while creating copyright-free illustrations.

Usage:
  export GEMINI_API_KEY="your-key-here"
  python scripts/transform_exercises_nanob.py                  # process all
  python scripts/transform_exercises_nanob.py --test           # test on one image
  python scripts/transform_exercises_nanob.py --test path.jpg  # test on specific image
  python scripts/transform_exercises_nanob.py --resume         # skip already-processed images
"""

import os
import sys
import time
from io import BytesIO
from pathlib import Path

from google import genai
from PIL import Image

PROMPT = (
    "Transform this exercise photo into a clean, modern fitness illustration. "
    "Use a simplified anatomical style with smooth body contours, flat colors, "
    "and clean outlines — like illustrations in a professional workout app. "
    "Show the person's full body pose and positioning EXACTLY as in the photo. "
    "Use a plain white background. Do not add any text or labels. "
    "The figure should look like an athletic, gender-neutral illustrated character."
)

MODEL = "gemini-2.0-flash-exp"  # supports image generation


def transform_image(client, image_path, output_path):
    """Transform a single exercise image using Nano Banana."""
    try:
        image = Image.open(image_path)

        response = client.models.generate_content(
            model=MODEL,
            contents=[PROMPT, image],
            config=genai.types.GenerateContentConfig(
                response_modalities=["Text", "Image"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                result = Image.open(BytesIO(part.inline_data.data))
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                result.save(output_path, quality=90)
                return True

        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False


def process_all(input_dir, output_dir, single_file=None, resume=False):
    """Process all exercise images or a single file."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Get a free key at https://ai.google.dev/ and run:")
        print('  export GEMINI_API_KEY="your-key-here"')
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    if single_file:
        rel = os.path.relpath(single_file, input_dir)
        out_path = os.path.join(output_dir, rel)
        print(f"Processing: {rel}")
        success = transform_image(client, single_file, out_path)
        print(f"{'OK' if success else 'FAIL'}: {rel} -> {out_path}")
        return

    # Collect all images
    images = []
    for root, dirs, files in os.walk(input_dir):
        for f in sorted(files):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                full_path = os.path.join(root, f)
                rel = os.path.relpath(full_path, input_dir)
                out_path = os.path.join(output_dir, rel)

                if resume and os.path.exists(out_path):
                    continue

                images.append((full_path, rel, out_path))

    total = len(images)
    success_count = 0
    fail_count = 0

    print(f"Processing {total} images...")

    for i, (img_path, rel, out_path) in enumerate(images):
        success = transform_image(client, img_path, out_path)
        if success:
            success_count += 1
        else:
            fail_count += 1
            print(f"  FAIL: {rel}")

        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  Progress: {i+1}/{total} (OK: {success_count}, FAIL: {fail_count})")

        # Rate limiting — adjust if you hit quota errors
        time.sleep(1)

    print(f"\nDone! Success: {success_count}, Failed: {fail_count}")


if __name__ == '__main__':
    base = Path(__file__).resolve().parent.parent
    input_dir = base / 'resources' / 'exercises' / 'images'
    output_dir = base / 'resources' / 'exercises' / 'images_illustrated'

    resume = '--resume' in sys.argv

    if '--test' in sys.argv:
        idx = sys.argv.index('--test')
        test_file = sys.argv[idx + 1] if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith('--') else str(input_dir / 'Barbell_Curl' / '0.jpg')
        process_all(str(input_dir), str(output_dir), single_file=test_file)
    else:
        process_all(str(input_dir), str(output_dir), resume=resume)
