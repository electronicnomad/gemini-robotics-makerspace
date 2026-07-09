import os
import sys

print("=========================================")
print("🧠 GEMINI ROBOTICS EMBEDDED SYSTEM CHECK")
print("=========================================")

print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

# 1. Check if google-genai is installed
print("\n--- 1. Library Installation Check ---")
try:
    from google import genai
    from google.genai import types
    print("✅ google-genai is successfully installed and importable!")
    print(f"   Library location: {genai.__file__}")
except ImportError as e:
    print(f"❌ google-genai import failed: {e}")
    print("   Reason: The package 'google-genai' is not installed in this specific Python environment.")
    print("   Fix: Run './venv/bin/pip install google-genai' or 'pip install -r requirements.txt' inside your active environment.")

# 2. Check environment variables
print("\n--- 2. Environment Variable Check ---")
api_key = os.environ.get("GEMINI_API_KEY")

# Check if .env file exists and parse it manually like our script does
if os.path.exists(".env"):
    print("ℹ️ Found .env file in directory. Parsing it manually...")
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        if key.startswith("export "):
                            key = key[7:].strip()
                        val = parts[1].strip().strip('"').strip("'")
                        if key == "GEMINI_API_KEY":
                            api_key = val
                            print(f"✅ Found GEMINI_API_KEY in .env file.")
    except Exception as e:
         print(f"❌ Error reading .env: {e}")
else:
    print("ℹ️ No .env file found in workspace.")

if api_key:
    print(f"✅ GEMINI_API_KEY is recognized!")
    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "Too Short"
    print(f"   Key value: {masked_key}")
    if "AIzaSy" not in api_key:
        print("ℹ️ Note: The key does not start with 'AIzaSy'. Some Google Cloud enterprise or Vertex credentials start with other prefixes like 'AQ.'.")
else:
    print("❌ GEMINI_API_KEY is NOT set or cannot be read!")
    print("   Fix: Create a .env file containing: GEMINI_API_KEY=your_actual_key_here")

# 3. Check network and client initialization
print("\n--- 3. Gemini Client Initialization Check ---")
if 'genai' in locals() and api_key:
    try:
        client = genai.Client(api_key=api_key)
        print("✅ GenAI Client initialized successfully!")
        
        # Test query to confirm network and credentials
        print("ℹ️ Running a small connectivity test with gemini-2.5-flash...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents="Say 'Connection Successful!'"
        )
        print(f"✅ API Response: {response.text.strip()}")
    except Exception as e:
        print(f"❌ Client initialization or API call failed: {e}")
else:
    print("⚠️ Skipping connectivity test due to missing library or API Key.")

print("=========================================")
