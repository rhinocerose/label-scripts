import csv
import os
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import urlparse
import time
import json
import re

# DigiKey API v4 configuration
API_URL = "https://api.digikey.com/services/partsearch/v4/partsearch"
TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"

# Environment variables - set these before running
CLIENT_ID = os.getenv('DIGIKEY_CLIENT_ID')
CLIENT_SECRET = os.getenv('DIGIKEY_CLIENT_SECRET')

def get_auth_token():
    """Get OAuth2 token from DigiKey API"""
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    data = {'grant_type': 'client_credentials'}
    response = requests.post(TOKEN_URL, auth=auth, data=data)
    response.raise_for_status()
    return response.json()['access_token']

def search_part(part_number, token):
    """Search for a part using DigiKey API v4"""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Build the search payload - using ManufacturerPartNumber as the key
    payload = {
        "Keywords": part_number,
        "SearchOptions": "ManufacturerPart",
        "RecordCount": 10,
        "RecordStartPosition": 0,
        "Sort": {
            "Option": "SortByDigiKeyPartNumber",
            "Direction": "Ascending",
            "SortParameterId": 0
        },
        "RequestedQuantity": 0
    }

    try:
        print(f"Sending API request for: {part_number}")
        response = requests.post(API_URL, json=payload, headers=headers)
        print(f"Received API response: {response.status_code}")
        
        # Save debug information
        debug_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "part_number": part_number,
            "request_payload": payload,
            "status_code": response.status_code,
            "response_text": response.text,
            "response_json": None
        }
        
        try:
            debug_data["response_json"] = response.json()
        except:
            pass  # Ignore if response is not JSON
            
        # Save debug info to file
        debug_filename = f"api_debug_{re.sub(r'[^a-zA-Z0-9]', '_', part_number)}.json"
        with open(debug_filename, 'w') as f:
            json.dump(debug_data, f, indent=4)
        print(f"Saved debug data to: {debug_filename}")
        
        if response.status_code != 200:
            print(f"API Error: {response.status_code}")
            return {"Parts": []}
            
        return response.json()
    except Exception as e:
        print(f"API Call Failed: {str(e)}")
        return {"Parts": []}

def get_footprint(parameters):
    """Extract footprint from parameters"""
    for param in parameters:
        param_name = param.get('Parameter', '').lower()
        if 'case' in param_name or 'package' in param_name or 'footprint' in param_name:
            return param.get('Value', 'N/A')
    return 'N/A'


def process_csv(input_file, output_file):
    """Process CSV file and search for parts using API v4"""
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET environment variables not set")
        return
        
    try:
        token = get_auth_token()
        print("Successfully obtained API token")
    except Exception as e:
        print(f"Failed to obtain API token: {str(e)}")
        return
           
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)
        
        # Write CSV header
        writer.writerow(['Original Part', 'Match Type', 'DigiKey Part', 
                       'Manufacturer', 'Footprint', 'Datasheet Link', 'Description'])
        
        # Process each row
        for row_idx, row in enumerate(reader):
            if not row or not row[0].strip():
                continue  # Skip empty rows
                
            original_part = row[0].strip()
            
            try:
                print(f"\n{'='*50}")
                print(f"Processing part #{row_idx+1}: {original_part}")
                
                # Search for part
                result = search_part(original_part, token)
                parts = result.get('Parts', [])
                print(f"API returned {len(parts)} parts")
                
                exact_match = None
                close_matches = []
                
                # Process each part in the response
                for part in parts:
                    dk_part = part.get('DigiKeyPartNumber', '')
                    manu_part = part.get('ManufacturerPartNumber', '')
                    desc = part.get('ProductDescription', '')[:50] + '...' if part.get('ProductDescription', '') else 'N/A'
                    
                    # Check for exact match in Manufacturer Part Number
                    if manu_part.lower() == original_part.lower():
                        exact_match = part
                        print(f"★ Exact match: {manu_part} | {desc}")
                    else:
                        # Consider as close match if input is in manufacturer part number
                        if original_part.lower() in manu_part.lower():
                            print(f"  • Close match: {manu_part} | {desc}")
                            close_matches.append(part)
                
                # Handle exact match
                if exact_match:
                    print("Found exact match!")
                    datasheet_url = exact_match.get('PrimaryDatasheet', 'N/A')
                    writer.writerow([
                        original_part,
                        'Exact',
                        exact_match['DigiKeyPartNumber'],
                        exact_match['Manufacturer']['Value'],
                        get_footprint(exact_match.get('Parameters', [])),
                        datasheet_url,
                        exact_match['ProductDescription']
                    ])

                # Handle close matches
                elif close_matches:
                    print(f"Found {len(close_matches)} close matches")
                    # Show top matches
                    for i, match in enumerate(close_matches[:5], 1):
                        manu_part = match.get('ManufacturerPartNumber', 'N/A')
                        print(f"{i}. {manu_part} - {match['ProductDescription'][:50]}...")
                    
                    selection = input("Enter selection number (or press Enter to skip): ")
                    if selection.isdigit() and 0 < int(selection) <= len(close_matches):
                        selected = close_matches[int(selection)-1]
                        datasheet_url = selected.get('PrimaryDatasheet', 'N/A')
                        writer.writerow([
                            original_part,
                            'Manual Selection',
                            selected['DigiKeyPartNumber'],
                            selected['Manufacturer']['Value'],
                            get_footprint(selected.get('Parameters', [])),
                            datasheet_url,
                            selected['ProductDescription']
                        ])
                    else:
                        print("No selection made - skipping")
                        writer.writerow([original_part, 'No selection', '', '', '', '', ''])
                # No matches found
                else:
                    print("No matches found")
                    writer.writerow([original_part, 'No match', '', '', '', '', ''])
                
                # Add delay to avoid rate limiting
                time.sleep(1)
                print(f"Finished processing {original_part}")
                print(f"{'='*50}\n")
            
            except Exception as e:
                print(f"Error processing {original_part}: {str(e)}")
                writer.writerow([original_part, 'Error', '', '', '', '', ''])
                time.sleep(1)

if __name__ == '__main__':
    print("DigiKey Part Search Script")
    print("=" * 50)
    
    # Get input and output filenames
    input_csv = input("Enter input CSV filename: ").strip()
    output_csv = input("Enter output CSV filename: ").strip()
    
    # Verify input file exists
    if not os.path.exists(input_csv):
        print(f"Error: Input file '{input_csv}' not found")
        exit(1)
    
    # Run the processor
    process_csv(input_csv, output_csv)
    print("\nProcessing complete. Results saved to", output_csv)