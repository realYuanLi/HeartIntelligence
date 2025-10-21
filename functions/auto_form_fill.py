"""
PDF Form Filling Module - Flask Blueprint
Handles PDF form upload, AI-powered field extraction, and form filling

Supports two types of PDFs:
1. Fillable PDFs (with form fields): Direct field filling
2. Static PDFs (without form fields): AI-powered text overlay with position detection
"""

from flask import Blueprint, request, jsonify, send_file
import io
import uuid
import json
import re
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black

pdf_forms_bp = Blueprint('pdf_forms', __name__)

_pdf_data_store = {}

_require_login = None
_username = None
_chatbot = None
_get_user_ehr_data = None
_analyze_cardiovascular = None
_analyze_clinical = None
_get_demographics = None


def init_pdf_forms(app, require_login_func, username_func, chatbot_class, 
                   get_user_ehr_data_func, analyze_cardiovascular_func,
                   analyze_clinical_func, get_demographics_func):
    """Initialize the PDF forms module with dependencies"""
    global _require_login, _username, _chatbot, _get_user_ehr_data
    global _analyze_cardiovascular, _analyze_clinical, _get_demographics
    
    _require_login = require_login_func
    _username = username_func
    _chatbot = chatbot_class
    _get_user_ehr_data = get_user_ehr_data_func
    _analyze_cardiovascular = analyze_cardiovascular_func
    _analyze_clinical = analyze_clinical_func
    _get_demographics = get_demographics_func
    
    app.register_blueprint(pdf_forms_bp)


def _determine_field_positions(fields, full_text, text_positions):
    """
    Use AI to determine where each field value should be placed on the PDF
    """
    field_positions = []
    
    try:
        # Get page dimensions
        page_info = text_positions[0] if text_positions else {'width': 612, 'height': 792, 'page': 0}
        page_width = page_info.get('width', 612)
        page_height = page_info.get('height', 792)
        
        # Prepare field information for AI (using field_key for consistent matching)
        field_info = []
        for field in fields:
            field_name = field.get('field_name', '')
            field_key = field.get('field_key', '')
            field_value = field.get('field_value', '')
            position_hint = field.get('position_hint', 'right')
            
            if field_value and field_value.strip():
                field_info.append({
                    'key': field_key,
                    'label': field_name,
                    'value': field_value,
                    'hint': position_hint
                })
        
        if not field_info:
            return field_positions
        
        # Use AI to estimate positions based on text content
        position_prompt = f"""Given a PDF form with the following text content, estimate the position where each field value should be written.

PDF Text:
{full_text[:2000]}

PDF Dimensions: {page_width} x {page_height} points

Fields to position:
{json.dumps(field_info, indent=2)}

For each field, estimate:
- page: Which page (0-indexed)
- x: Horizontal position in points (0 = left edge, typically answer boxes start around 200-300)
- y: Vertical position in points (0 = bottom edge, so higher numbers are towards top)

Consider:
- Field labels are usually on the left, answers go to the right or below
- Standard margins are around 50-70 points
- Typical line height is 12-15 points
- Multiple fields are usually vertically spaced by 20-40 points

Return ONLY a JSON array with EXACT field keys:
[
  {{"key": "full_name", "page": 0, "x": 250, "y": 700}},
  {{"key": "date_of_birth", "page": 0, "x": 250, "y": 660}},
  ...
]

IMPORTANT: Use the EXACT 'key' values from the fields list above. Do not modify them."""

        messages = [{"role": "user", "content": position_prompt}]
        resp = _chatbot.llm_reply(messages)
        ai_response = resp.content if hasattr(resp, "content") else str(resp)
        
        # Parse AI response
        try:
            json_match = re.search(r'\[.*\]', ai_response, re.DOTALL)
            if json_match:
                positions = json.loads(json_match.group())
                
                # Create position map using field_key for consistent matching
                position_map = {pos['key']: pos for pos in positions}
                
                # Map positions to field values using field_key
                for field in fields:
                    field_key = field.get('field_key', '')
                    field_name = field.get('field_name', '')
                    field_value = field.get('field_value', '')
                    
                    if field_value and field_value.strip() and field_key in position_map:
                        pos = position_map[field_key]
                        field_positions.append({
                            'page': pos.get('page', 0),
                            'x': pos.get('x', 250),
                            'y': pos.get('y', page_height - 100),
                            'value': field_value
                        })
                        print(f"✓ Positioned '{field_name}' ({field_key}) at ({pos.get('x')}, {pos.get('y')})")
                
                print(f"✓ Successfully positioned {len(field_positions)} fields using AI")
        except Exception as e:
            print(f"⚠ Error parsing AI position response: {e}")
            # Fallback: simple vertical stacking
            y_pos = page_height - 100
            for field in fields:
                field_value = field.get('field_value', '')
                if field_value and field_value.strip():
                    field_positions.append({
                        'page': 0,
                        'x': 250,
                        'y': y_pos,
                        'value': field_value
                    })
                    y_pos -= 25
    
    except Exception as e:
        print(f"⚠ Error determining field positions: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: simple layout
        page_height = 792
        y_pos = page_height - 100
        for field in fields:
            field_value = field.get('field_value', '')
            if field_value and field_value.strip():
                field_positions.append({
                    'page': 0,
                    'x': 250,
                    'y': y_pos,
                    'value': field_value
                })
                y_pos -= 25
    
    return field_positions


def _generate_field_values_with_llm(fields_data, user):
    """
    Use LLM to generate appropriate values for form fields based on EHR data
    """
    try:
        # Prepare field information for the LLM (using field_key as canonical identifier)
        field_info = []
        for field in fields_data:
            field_key = field.get('field_key', '')
            field_name = field.get('field_name', '')
            field_info.append({
                'key': field_key,
                'label': field_name
            })
        field_descriptions = "\n".join([f"- {f['key']}: {f['label']}" for f in field_info])
        
        # Prepare patient context
        patient_context = ""
        EHR_DATA = _get_user_ehr_data(user) if _get_user_ehr_data else None
        
        if EHR_DATA:
            # Extract relevant demographics and health data
            demographics = _get_demographics()
            
            patient_context = f"""
Patient Information Available:
- Name: {demographics.get('name', 'N/A')}
- Birth Date: {demographics.get('birth_date', 'N/A')}
- Age: {demographics.get('age', 'N/A')}
- Sex: {demographics.get('sex', 'N/A')}
"""
            
            # Add cardiovascular data if available
            cardio = _analyze_cardiovascular()
            if cardio.get('resting_heart_rate'):
                rhr = cardio['resting_heart_rate']
                patient_context += f"\nResting Heart Rate: {rhr.get('current', 'N/A')} {rhr.get('unit', '')}"
            
            if cardio.get('blood_pressure'):
                bp = cardio['blood_pressure']
                patient_context += f"\nBlood Pressure: {bp.get('current', 'N/A')}"
            
            # Add medications and conditions
            clinical = _analyze_clinical()
            if clinical.get('medications'):
                meds = [med['name'] for med in clinical['medications'][:5]]
                patient_context += f"\nCurrent Medications: {', '.join(meds)}"
            
            if clinical.get('conditions'):
                conditions = [cond['name'] for cond in clinical['conditions'][:5]]
                patient_context += f"\nMedical Conditions: {', '.join(conditions)}"
            
            if clinical.get('allergies'):
                allergies = [allergy['name'] for allergy in clinical['allergies'][:5]]
                patient_context += f"\nAllergies: {', '.join(allergies)}"
        else:
            patient_context = """
No patient data available. Please generate realistic sample data for a test patient.
Use: Kevin Smith, DOB: 01/15/1995, Male, Phone: (555) 123-4567, Email: kevin.smith@example.com
Address: 123 Main Street, Boston, MA 02101
"""
        
        # Generate prompt for LLM
        generation_prompt = f"""You are filling out a medical form. Based on the patient information provided, generate appropriate values for each field.

{patient_context}

Form Fields to Fill (key: label):
{field_descriptions}

Please provide appropriate values for each field in JSON format using the EXACT field keys:
{{
  "field_key_1": "value_1",
  "field_key_2": "value_2",
  ...
}}

Guidelines:
- Use actual patient data when available
- For contact information, use realistic formats
- For dates, use MM/DD/YYYY format
- For medical information, be accurate and professional
- If information is not available, use "N/A" or leave appropriate fields empty
- Keep responses concise and relevant

IMPORTANT: Use the EXACT field keys (e.g., "full_name", "date_of_birth") from the list above, not the labels.

Return ONLY the JSON object, no other text."""

        messages = [{"role": "user", "content": generation_prompt}]
        resp = _chatbot.llm_reply(messages)
        ai_response = resp.content if hasattr(resp, "content") else str(resp)
        
        print(f"LLM Response for field generation: {ai_response[:200]}...")
        
        # Parse the AI response
        try:
            # Extract JSON object from response
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', ai_response, re.DOTALL)
            if json_match:
                generated_values = json.loads(json_match.group())
                
                # Update fields with generated values using field_key
                for field in fields_data:
                    field_key = field.get('field_key', '')
                    field_name = field.get('field_name', '')
                    if field_key in generated_values:
                        field['field_value'] = generated_values[field_key]
                        print(f"✓ Generated value for '{field_name}' ({field_key}): {generated_values[field_key][:50]}...")
                
                print(f"✓ Successfully generated {len(generated_values)} field values using LLM")
        except Exception as e:
            print(f"⚠ Error parsing LLM response for field values: {e}")
            # Continue with empty values if parsing fails
    
    except Exception as e:
        print(f"⚠ Error generating field values with LLM: {e}")
        import traceback
        traceback.print_exc()
    
    return fields_data


@pdf_forms_bp.route("/api/pdf/upload", methods=["POST"])
def api_pdf_upload():
    """Upload and analyze a PDF form"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    if 'file' not in request.files:
        return jsonify(success=False, message="No file provided"), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, message="No file selected"), 400
    
    if not file.filename.endswith('.pdf'):
        return jsonify(success=False, message="File must be a PDF"), 400
    
    try:
        # Read PDF content
        pdf_content = file.read()
        pdf_reader = PdfReader(io.BytesIO(pdf_content))
        
        # Check if PDF has form fields (Option B: fillable PDF)
        has_form_fields = False
        form_fields = {}
        
        if '/AcroForm' in pdf_reader.trailer['/Root']:
            try:
                fields = pdf_reader.get_fields()
                if fields:
                    has_form_fields = True
                    form_fields = fields
                    print(f"✓ Detected fillable PDF with {len(fields)} form fields")
            except:
                pass
        
        fields_data = []
        
        if has_form_fields:
            # Option B: Extract form field names directly
            for field_name, field_info in form_fields.items():
                # Convert field name to readable label
                label = field_name.replace('_', ' ').title()
                fields_data.append({
                    "field_name": label,
                    "field_key": field_name,  # Original field key for filling
                    "field_value": "",
                    "field_type": "text"
                })
        else:
            # Option A: Extract text and use AI to identify fields (static PDF)
            text_content = ""
            text_with_positions = []
            
            for page_num, page in enumerate(pdf_reader.pages):
                text_content += page.extract_text() + "\n"
                
                # Extract text with positions for better alignment
                try:
                    if '/Contents' in page:
                        page_text = page.extract_text()
                        text_with_positions.append({
                            'page': page_num,
                            'text': page_text,
                            'width': float(page.mediabox.width),
                            'height': float(page.mediabox.height)
                        })
                except:
                    pass
            
            # Use AI to analyze the form and extract fields with positions
            analysis_prompt = f"""Analyze this PDF form and identify the fields that need to be filled.

PDF Content:
{text_content[:3000]}

Please identify all form fields and estimate where the answer should be written.
For each field, provide:
- field_name: The label or question (e.g., "Full Name", "Date of Birth")
- field_key: A unique identifier derived from field_name (lowercase, underscores)
- position_hint: Where the answer appears relative to the label ("right", "below", "inline")

Return a JSON array in this format:
[
  {{"field_name": "Full Name", "field_key": "full_name", "field_value": "", "field_type": "text", "position_hint": "right"}},
  {{"field_name": "Date of Birth", "field_key": "date_of_birth", "field_value": "", "field_type": "text", "position_hint": "right"}},
  ...
]

Only return the JSON array, no other text."""

            messages = [{"role": "user", "content": analysis_prompt}]
            resp = _chatbot.llm_reply(messages)
            ai_response = resp.content if hasattr(resp, "content") else str(resp)
            
            # Parse the AI response to extract fields
            try:
                json_match = re.search(r'\[.*\]', ai_response, re.DOTALL)
                if json_match:
                    fields_data = json.loads(json_match.group())
                    # Ensure field_key exists for all fields
                    for field in fields_data:
                        if 'field_key' not in field:
                            field['field_key'] = field.get('field_name', '').lower().replace(' ', '_')
                        if 'position_hint' not in field:
                            field['position_hint'] = 'right'
            except:
                pass
            
            # Store text with positions for later use
            if text_with_positions:
                pdf_store_data = {
                    'text_positions': text_with_positions,
                    'full_text': text_content
                }
        
        # Use LLM to generate appropriate values for all fields
        if fields_data:
            user = _username()
            fields_data = _generate_field_values_with_llm(fields_data, user)
        
        # Store the PDF and extracted data
        user = _username()
        pdf_id = uuid.uuid4().hex[:12]
        store_data = {
            'pdf_id': pdf_id,
            'original_content': pdf_content,
            'has_form_fields': has_form_fields,
            'fields': fields_data,
            'filename': file.filename
        }
        
        # Add text position data for static PDFs
        if not has_form_fields and 'pdf_store_data' in locals():
            store_data.update(pdf_store_data)
        
        _pdf_data_store[user] = store_data
        
        return jsonify(success=True, pdf_id=pdf_id, fields=fields_data, is_fillable=has_form_fields)
        
    except Exception as e:
        print(f"Error processing PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify(success=False, message=f"Error processing PDF: {str(e)}"), 500


@pdf_forms_bp.route("/api/pdf/generate", methods=["POST"])
def api_pdf_generate():
    """Generate a filled PDF with the provided data"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    user = _username()
    if user not in _pdf_data_store:
        return jsonify(success=False, message="No PDF data found"), 404
    
    try:
        data = request.get_json(force=True)
        fields = data.get('fields', [])
        pdf_store = _pdf_data_store[user]
        
        # Check if this is a fillable PDF
        if pdf_store.get('has_form_fields', False):
            # Option B: Fill form fields directly
            pdf_reader = PdfReader(io.BytesIO(pdf_store['original_content']))
            pdf_writer = PdfWriter()
            
            # Clone pages and form from reader
            pdf_writer.append(pdf_reader)
            
            # Prepare field values dictionary
            field_values = {}
            for field in fields:
                field_key = field.get('field_key', '')
                if not field_key:
                    # Try to derive from field_name
                    field_key = field.get('field_name', '').lower().replace(' ', '_')
                field_value = field.get('field_value', '')
                if field_value:
                    field_values[field_key] = field_value
            
            # Update all fields at once
            if field_values:
                pdf_writer.update_page_form_field_values(
                    pdf_writer.pages[0], 
                    field_values
                )
            
            # Write to buffer
            output_buffer = io.BytesIO()
            pdf_writer.write(output_buffer)
            output_buffer.seek(0)
            
            _pdf_data_store[user]['filled_pdf'] = output_buffer.getvalue()
            
        else:
            # Option A: Overlay text on static PDF
            pdf_reader = PdfReader(io.BytesIO(pdf_store['original_content']))
            pdf_writer = PdfWriter()
            
            # Get text positions if available
            text_positions = pdf_store.get('text_positions', [])
            full_text = pdf_store.get('full_text', '')
            
            # Use AI to determine positions for each field value
            field_positions = _determine_field_positions(fields, full_text, text_positions)
            
            # Process each page
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                page_width = float(page.mediabox.width)
                page_height = float(page.mediabox.height)
                
                # Create overlay with field values
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=(page_width, page_height))
                can.setFillColor(black)
                can.setFont("Helvetica", 10)
                
                # Add field values to this page
                fields_on_page = [f for f in field_positions if f.get('page', 0) == page_num]
                for field_pos in fields_on_page:
                    x = field_pos.get('x', 50)
                    y = field_pos.get('y', page_height - 100)
                    value = field_pos.get('value', '')
                    
                    if value and value.strip():
                        # Draw the text
                        can.drawString(x, y, value[:100])  # Limit length
                
                can.save()
                
                # Merge overlay with original page
                packet.seek(0)
                overlay_pdf = PdfReader(packet)
                if len(overlay_pdf.pages) > 0:
                    page.merge_page(overlay_pdf.pages[0])
                
                pdf_writer.add_page(page)
            
            # Write final PDF
            output_buffer = io.BytesIO()
            pdf_writer.write(output_buffer)
            output_buffer.seek(0)
            
            _pdf_data_store[user]['filled_pdf'] = output_buffer.getvalue()
        
        return jsonify(success=True, message="PDF generated successfully")
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify(success=False, message=f"Error generating PDF: {str(e)}"), 500


@pdf_forms_bp.route("/api/pdf/download")
def api_pdf_download():
    """Download the filled PDF"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    user = _username()
    if user not in _pdf_data_store or 'filled_pdf' not in _pdf_data_store[user]:
        return jsonify(success=False, message="No filled PDF available"), 404
    
    try:
        filled_pdf = _pdf_data_store[user]['filled_pdf']
        original_filename = _pdf_data_store[user].get('filename', 'form.pdf')
        output_filename = original_filename.replace('.pdf', '_filled.pdf')
        
        return send_file(
            io.BytesIO(filled_pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_filename
        )
        
    except Exception as e:
        print(f"Error downloading PDF: {e}")
        return jsonify(success=False, message=f"Error downloading PDF: {str(e)}"), 500

