#!/usr/bin/env python3
"""
Test script to verify line break handling in the chat application.
"""

import requests
import json
import time

def test_line_breaks():
    base_url = "http://localhost:8000"
    
    print("Testing line break functionality...")
    
    # Create a session for maintaining login state
    session = requests.Session()
    
    # Test 0: Login first
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
    
    # Test 1: Create a new session
    print("\n1. Creating new session...")
    response = session.post(f"{base_url}/api/new_session", json={})
    if response.status_code == 200:
        session_data = response.json()
        session_id = session_data.get('session_id')
        print(f"   Session created: {session_id}")
    else:
        print(f"   Failed to create session: {response.status_code}")
        return
    
    # Test 2: Send a message with single line breaks
    print("\n2. Testing single line breaks (\\n)...")
    test_message_1 = "Line 1\nLine 2\nLine 3"
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_1
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        print(f"   Assistant message preview: {result.get('assistant_message', '')[:100]}...")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    time.sleep(1)
    
    # Test 3: Send a message with double line breaks
    print("\n3. Testing double line breaks (\\n\\n)...")
    test_message_2 = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_2
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        print(f"   Assistant message preview: {result.get('assistant_message', '')[:100]}...")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    time.sleep(1)
    
    # Test 4: Send a message with mixed content (markdown)
    print("\n4. Testing mixed content with markdown...")
    test_message_3 = "**Bold text** with line breaks.\n\nHere's a list:\n- Item 1\n- Item 2\n- Item 3\n\n*Italic text* with a line break.\n\nFinal paragraph."
    response = session.post(f"{base_url}/api/message", json={
        "session_id": session_id,
        "message": test_message_3
    })
    if response.status_code == 200:
        result = response.json()
        print(f"   Response: {result.get('success', False)}")
        print(f"   Assistant message preview: {result.get('assistant_message', '')[:100]}...")
    else:
        print(f"   Failed to send message: {response.status_code}")
    
    # Test 5: Get the full conversation to see how it's rendered
    print("\n5. Retrieving full conversation...")
    response = session.get(f"{base_url}/api/session/{session_id}")
    if response.status_code == 200:
        session_data = response.json()
        conversation = session_data.get('conversation', [])
        print(f"   Found {len(conversation)} messages in conversation")
        
        for i, msg in enumerate(conversation):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            print(f"   Message {i+1} ({role}): {content[:50]}...")
    else:
        print(f"   Failed to retrieve conversation: {response.status_code}")
    
    print("\nTest completed!")

if __name__ == "__main__":
    test_line_breaks()
