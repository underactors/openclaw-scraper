import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get('NOTION_API_KEY')
db_id = os.environ.get('NOTION_LEADS_DB_ID')

# Format the database ID properly (add dashes if missing)
if db_id and '-' not in db_id:
    # Convert 38ddcd5d6a5d4b4b9eb395d6de84beb3 to 38ddcd5d-6a5d-4b4b-9eb3-95d6de84beb3
    formatted_id = f"{db_id[0:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:]}"
else:
    formatted_id = db_id

print(f"Original ID:  {db_id}")
print(f"Formatted ID: {formatted_id}\n")

if not api_key or not db_id:
    print("ERROR: Missing credentials")
    exit(1)

headers = {
    'Authorization': f'Bearer {api_key}',
    'Notion-Version': '2025-09-03'
}

for test_id in [formatted_id, db_id]:
    print(f"\nTrying: {test_id}")
    print("-" * 60)
    try:
        url = f'https://api.notion.com/v1/databases/{test_id}'
        resp = requests.get(url, headers=headers)
        
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            props = data.get('properties', {})
            print(f'✅ SUCCESS! Found {len(props)} properties:')
            print('=' * 60)
            for name, info in sorted(props.items()):
                prop_type = info.get('type', 'unknown')
                print(f'{prop_type:20s} → {name}')
            print('=' * 60)
            break
        else:
            error_data = resp.json()
            print(f'❌ Error: {error_data.get("code", "unknown")}')
            print(f'   Message: {error_data.get("message", "no message")}')
        
    except Exception as e:
        print(f'❌ Exception: {e}')