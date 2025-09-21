#!/usr/bin/env python3
"""
Test script to verify that markdown formatting still works correctly after line break changes.
"""

import requests
import json
import time

def test_markdown_formatting():
    base_url = "http://localhost:8000"
    
    print("Testing markdown formatting functionality...")
    
    # Create a session for maintaining login state
    session = requests.Session()
    
    # Login first
    print("\n0. Logging in...")
    login_response = session.post(f"{base_url}/api/login", json={
        "username": "test",
        "password": "111"
    })
    if login_response.status_code == 200:
        login_data = login_response.json()
        print(f"   Login successful: {login_data.get('success', False)}")
    else:
        print(f"   Failed to login: {login_response.status_code}")
        return
    
    # Create a new session
    print("\n1. Creating new session...")
    response = session.post(f"{base_url}/api/new_session", json={})
    if response.status_code == 200:
        session_data = response.json()
        session_id = session_data.get('session_id')
        print(f"   Session created: {session_id}")
    else:
        print(f"   Failed to create session: {response.status_code}")
        return
    
    # Test 1: Bold and italic text
    print("\n2. Testing bold and italic formatting...")
    test_message_1 = "Please format this text: **This should be bold** and *this should be italic* and ***this should be both***."
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_1
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        assistant_msg = result.get('assistant_message', '')
        print(f"   Assistant response contains bold/italic: {'**' in assistant_msg or '<strong>' in assistant_msg or '<em>' in assistant_msg}")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    time.sleep(1)
    
    # Test 2: Lists (bulleted and numbered)
    print("\n3. Testing lists...")
    test_message_2 = "Please create a list with these items:\n- First item\n- Second item\n- Third item\n\nAnd a numbered list:\n1. First numbered item\n2. Second numbered item\n3. Third numbered item"
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_2
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        assistant_msg = result.get('assistant_message', '')
        print(f"   Assistant response contains lists: {'<ul>' in assistant_msg or '<ol>' in assistant_msg or '- ' in assistant_msg}")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    time.sleep(1)
    
    # Test 3: Code formatting
    print("\n4. Testing code formatting...")
    test_message_3 = "Please format this code: `inline code` and a code block:\n```python\nprint('Hello, World!')\nreturn True\n```"
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_3
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        assistant_msg = result.get('assistant_message', '')
        print(f"   Assistant response contains code: {'<code>' in assistant_msg or '<pre>' in assistant_msg}")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    time.sleep(1)
    
    # Test 4: Mixed content with line breaks and formatting
    print("\n5. Testing mixed content with line breaks and formatting...")
    test_message_4 = "**Bold paragraph** with content.\n\nHere's a list:\n- **Bold item**\n- *Italic item*\n- `Code item`\n\n*Italic paragraph* with a line break.\n\nFinal paragraph with `inline code`."
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_4
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        assistant_msg = result.get('assistant_message', '')
        print(f"   Assistant response length: {len(assistant_msg)} characters")
        print(f"   Contains formatting: {'**' in assistant_msg or '<strong>' in assistant_msg or '<em>' in assistant_msg or '<code>' in assistant_msg}")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    # Get the full conversation to see how it's rendered
    print("\n6. Retrieving full conversation...")
    response = session.get(f"{base_url}/api/session/{session_id}")
    if response.status_code == 200:
        session_data = response.json()
        conversation = session_data.get('conversation', [])
        print(f"   Found {len(conversation)} messages in conversation")
        
        # Show the last assistant message to see formatting
        if len(conversation) >= 2:
            last_assistant = conversation[-1]
            if last_assistant.get('role') == 'assistant':
                content = last_assistant.get('content', '')
                print(f"   Last assistant message preview: {content[:200]}...")
                print(f"   Contains HTML tags: {'<' in content and '>' in content}")
    else:
        print(f"   Failed to retrieve conversation: {response.status_code}")
    
    print("\nMarkdown formatting test completed!")

if __name__ == "__main__":
    test_markdown_formatting()
