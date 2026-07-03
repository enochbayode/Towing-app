import asyncio
import httpx
import time

# --- 9JALINGO CONFIGURATION ---
NINEJALINGO_API_KEY = "your_9jalingo_api_key_here"  # 🔴 Paste your key here
NINEJALINGO_URL = "https://api.9jalingo.org/v1/tts" # 🔴 Verify this exact URL in their docs

async def test_9jalingo_speed():
    test_text = "Bawo ni? Aago melo ni ipade wa loni?" 
    
    headers = {
        "Authorization": f"Bearer {NINEJALINGO_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 🔴 Verify the payload structure in their API docs
    payload = {
        "text": test_text,
        "language": "yo",           # They likely require a language code
        "voice": "standard_female", # Replace with their actual voice ID
        "format": "mp3"
    }

    print(f"--> Sending Yoruba text to 9jalingo.org: '{test_text}'")
    
    start_time = time.time()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(NINEJALINGO_URL, json=payload, headers=headers, timeout=60.0)
            
        elapsed_time = time.time() - start_time

        if response.status_code == 200:
            print(f"✅ SUCCESS! Audio generated in {elapsed_time:.2f} seconds.")
            
            with open("9jalingo_test.mp3", "wb") as f:
                f.write(response.content)
            print("--> Saved audio to '9jalingo_test.mp3'.")
            
        else:
            print(f"❌ ERROR {response.status_code}: {response.text}")

    except Exception as e:
        print(f"❌ CRASH: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_9jalingo_speed())