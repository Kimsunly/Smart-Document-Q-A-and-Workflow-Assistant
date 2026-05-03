import requests
import json

try:
    response = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={"model": "llama3.2:3b", "prompt": "What is 2+2?", "stream": False},
        timeout=30
    )
    print("Status:", response.status_code)
    print("Response:", response.text[:500])

    # Parse and pretty print
    try:
        data = response.json()
        print("\nParsed JSON:")
        print(json.dumps(data, indent=2)[:500])
    except:
        pass

except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
