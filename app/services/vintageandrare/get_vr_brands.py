"""
Revised content for get_vr_brands.py (Focus: "XY " search terms, HTML parsing)

Because the Vintage & Rare (V&R) website uses AJAX to suggest brand names, this script fetches brand suggestions based on user input, 
parses the HTML response, and refines the search process iteratively. 
It handles both initial brand loading and gap-filling for brand names that may not have been captured in previous runs.

"""

import re
import requests
import json
import time
import string
from pathlib import Path
from bs4 import BeautifulSoup # For HTML parsing
import getpass

# URL for the AJAX endpoint
AJAX_URL = "https://www.vintageandrare.com/ajax/get_suggested_brands_name"
SPECIFIC_REFERER_PAGE = 'https://www.vintageandrare.com/instruments/add_edit_item'
LOGIN_URL = "https://www.vintageandrare.com/do_login"
HOME_URL = "https://www.vintageandrare.com"

HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://www.vintageandrare.com',
    'Referer': SPECIFIC_REFERER_PAGE,
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

def parse_brand_response_html(response_text, search_term=""):
    """
    Parses the V&R brand suggestion HTML response using BeautifulSoup.
    Extracts brand name and ID from <li> elements.
    Returns a list of dictionaries: [{"name": "Brand Name", "id": 123}, ...].
    """
    brands_data = []
    brand_names_seen = set() 

    if response_text is None or response_text.strip() == "":
        print(f"    DEBUG: Empty or None response text for term '{search_term}'.")
        return brands_data

    # print(f"    DEBUG: Raw response for '{search_term}' (first 300 chars): {response_text[:300]}")
    
    soup = BeautifulSoup(response_text, 'lxml')
    list_items = soup.find_all('li')

    if not list_items:
        print(f"    DEBUG: No <li> items found for '{search_term}'. Raw response (first 300 chars): {response_text[:300]}")
        # Fallback for potential "ID!::!Name" format if V&R mixes response types
        if "!::!" in response_text:
            parts = response_text.split("!::!", 1)
            if len(parts) == 2:
                brand_id_str, brand_name = parts[0].strip(), parts[1].strip()
                try:
                    brand_id = int(brand_id_str)
                    if brand_name and brand_name not in brand_names_seen:
                        brands_data.append({"name": brand_name, "id": brand_id})
                        brand_names_seen.add(brand_name)
                except ValueError: # ID wasn't an int
                    if brand_name and brand_name not in brand_names_seen:
                         brands_data.append({"name": brand_name, "id": None})
                         brand_names_seen.add(brand_name)
        return brands_data

    for item in list_items:
        onclick_attr = item.get('onclick', '')
        brand_name_from_text = item.get_text(strip=True)
        brand_id = None
        brand_name_for_dict = brand_name_from_text 

        match = re.search(r"set_autosuggest_brands\s*\(\s*'((?:[^']|\\')*)'\s*,\s*(\d+)\s*\)", onclick_attr)
        if match:
            name_from_onclick = match.group(1).replace("\\'", "'")
            id_from_onclick = int(match.group(2))
            brand_name_for_dict = name_from_onclick
            brand_id = id_from_onclick
        
        if brand_name_for_dict and brand_name_for_dict not in brand_names_seen:
            brands_data.append({"name": brand_name_for_dict, "id": brand_id})
            brand_names_seen.add(brand_name_for_dict)

    if not brands_data and list_items:
        print(f"    DEBUG: Found <li> items for '{search_term}' but failed to extract brand data (check HTML structure).")
    return brands_data

def fetch_brands_for_term(search_term, session):
    payload = {'str': search_term}
    print(f"  Fetching brands with payload: {payload}")
    try:
        response = session.post(AJAX_URL, headers=HEADERS, data=payload, timeout=15)
        print(f"    Response status for '{search_term}': {response.status_code}")
        if response.status_code == 200:
            return parse_brand_response_html(response.text, search_term)
        else:
            print(f"    Error: Received status {response.status_code} for term '{search_term}'. Response: {response.text[:300]}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"    Error fetching brands for term '{search_term}': {e}")
        return []

def generate_targeted_prefixes(current_sorted_brand_names: list, 
                               attempted_search_prefixes: set, 
                               target_len: int) -> set:
    """
    Generates new search prefixes of a target length to explore gaps.
    Prefixes will be of the form 'ABC ' or 'ABCD ' (no internal spaces before the final one).
    """
    new_prefixes_to_try = set()
    if not current_sorted_brand_names:
        return new_prefixes_to_try

    # Strategy 1: Generate prefixes of target_len from the start of existing names
    for name in current_sorted_brand_names:
        if len(name) >= target_len:
            prefix_chars_candidate = name[:target_len]
            # *** BUG FIX: Ensure the candidate characters do NOT contain spaces ***
            if " " not in prefix_chars_candidate: 
                prefix = prefix_chars_candidate + " " 
                if prefix not in attempted_search_prefixes:
                    new_prefixes_to_try.add(prefix)
            # else:
                # print(f"    DEBUG: Skipped generating from '{name}' for target_len {target_len} due to internal space in '{prefix_chars_candidate}'")
    
    # Strategy 2: Interpolate alphabetically if names share a prefix of (target_len - 1)
    if target_len > 1: # Interpolation needs a base prefix
        for i in range(len(current_sorted_brand_names) - 1):
            name1 = current_sorted_brand_names[i]
            name2 = current_sorted_brand_names[i+1]

            lcp_val = "" # Longest Common Prefix base
            for k in range(min(len(name1), len(name2))):
                if name1[k].lower() == name2[k].lower():
                    # Use original casing from name1 for the LCP base,
                    # as V&R might be case sensitive in how it stores/displays, even if search is not.
                    lcp_val += name1[k] 
                else:
                    break
            
            # We are interested if the LCP is exactly one shorter than our target prefix length
            if len(lcp_val) == target_len - 1:
                # And ensure this LCP itself doesn't have spaces (unlikely but good check)
                if " " in lcp_val:
                    # print(f"    DEBUG: Skipped LCP '{lcp_val}' for interpolation due to internal space.")
                    continue

                char1_after_lcp = name1[len(lcp_val)] if len(lcp_val) < len(name1) and name1[len(lcp_val)].isalpha() else None
                char2_after_lcp = name2[len(lcp_val)] if len(lcp_val) < len(name2) and name2[len(lcp_val)].isalpha() else None

                if char1_after_lcp and char2_after_lcp:
                    # Add prefixes derived directly from name1 and name2 if they form a clean target_len prefix
                    p1_candidate_chars = lcp_val + name1[len(lcp_val)]
                    if " " not in p1_candidate_chars: # Check before adding space
                        p1_candidate = p1_candidate_chars + " "
                        if p1_candidate not in attempted_search_prefixes: 
                            new_prefixes_to_try.add(p1_candidate)
                    
                    p2_candidate_chars = lcp_val + name2[len(lcp_val)]
                    if " " not in p2_candidate_chars: # Check before adding space
                        p2_candidate = p2_candidate_chars + " "
                        if p2_candidate not in attempted_search_prefixes: 
                            new_prefixes_to_try.add(p2_candidate)

                    # Interpolate if there's an alphabetical gap greater than 1
                    ord1 = ord(char1_after_lcp.lower())
                    ord2 = ord(char2_after_lcp.lower())
                    
                    if ord2 > ord1 + 1: 
                        for o in range(ord1 + 1, ord2):
                            inter_char = chr(o)
                            if inter_char.isalpha(): 
                                # lcp_val should be clean (no spaces). inter_char is a single char.
                                inter_prefix_str = lcp_val + inter_char + " "
                                if inter_prefix_str not in attempted_search_prefixes:
                                    new_prefixes_to_try.add(inter_prefix_str)
                                    
    final_generated_prefixes = {p for p in new_prefixes_to_try if p not in attempted_search_prefixes}
    if final_generated_prefixes:
        example_prefix = next(iter(final_generated_prefixes)) if final_generated_prefixes else "N/A"
        print(f"Generated {len(final_generated_prefixes)} new unique prefixes of target length {target_len} (e.g., '{example_prefix.strip()} ') for refinement.")
    return final_generated_prefixes

# --- MODIFIED Main Mining Function ---
def mine_all_vr_brands_iterative(username, password, 
                                 initial_brands_file: str, # Path to your JSON file from the previous run
                                 output_filename="vr_brands_REFINED.json"):
    all_brands_dict = {} # Key: brand_name, Value: {"name": name, "id": id}
    attempted_search_terms = set() # Track all search terms used across all phases

    # 1. Load initial brands from the provided JSON file
    initial_brands_loaded_count = 0
    if Path(initial_brands_file).is_file():
        try:
            with open(initial_brands_file, 'r', encoding='utf-8') as f:
                initial_brands_list = json.load(f) # This is the list of dicts from your file
            for brand_info in initial_brands_list: # brand_info is like {"name": "...", "id": ...}
                name = brand_info.get("name")
                if name:
                    if name not in all_brands_dict or \
                       (brand_info.get("id") is not None and all_brands_dict[name].get("id") is None):
                        all_brands_dict[name] = brand_info
            initial_brands_loaded_count = len(all_brands_dict)
            print(f"Successfully loaded {initial_brands_loaded_count} unique brands from '{initial_brands_file}'.")
        except Exception as e:
            print(f"Could not load or parse initial brands from '{initial_brands_file}': {e}. Starting fresh.")
    else:
        print(f"Initial brands file '{initial_brands_file}' not found. Starting fresh.")
        print("Consider running a broader search first if this is not intended.")

    # (Session setup and login logic - ensure this is robust from previous versions)
    with requests.Session() as session:
        print(f"\nAttempting login for user: {username} to refine brand list...")
        try:
            session.get(HOME_URL, headers=HEADERS, timeout=10) # Prime cookies
            login_data = {'username': username, 'pass': password, 'open_where': 'header'}
            login_headers = HEADERS.copy()
            login_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            login_headers['Referer'] = HOME_URL
            login_response = session.post(LOGIN_URL, headers=login_headers, data=login_data, allow_redirects=True, timeout=15)
            print(f"Login POST status: {login_response.status_code}, Final URL: {login_response.url}")
            if "login_failed" in login_response.url or ("pass" in login_response.text.lower() and "username" in login_response.text.lower()):
                 print("Login appears to have FAILED. Results might be limited.")
            else:
                 print("Login likely successful or session changed.")
            # Try to visit the referer page after login attempt
            page_response = session.get(SPECIFIC_REFERER_PAGE, headers=HEADERS, timeout=10)
            print(f"Visit status for '{SPECIFIC_REFERER_PAGE}' post-login attempt: {page_response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Error during login/setup: {e}. Proceeding with current session state.")
        time.sleep(0.5)

        # ---- Iterative Refinement Phases ----
        prefix_lengths_to_attempt = [3, 4] # First 3-char prefixes, then 4-char

        for target_len in prefix_lengths_to_attempt:
            print(f"\n--- Starting Refinement Phase: Target Prefix Length {target_len} ---")
            # Get current known brand names, sorted, for generating new prefixes
            current_sorted_names = sorted(list(all_brands_dict.keys()), key=str.lower)
            
            prefixes_to_try_this_phase = generate_targeted_prefixes(current_sorted_names, 
                                                                  attempted_search_terms, 
                                                                  target_len)
            
            if not prefixes_to_try_this_phase:
                print(f"No new unique prefixes of length {target_len} generated to try for this phase.")
                continue

            print(f"Attempting {len(prefixes_to_try_this_phase)} new prefixes of target length {target_len}...")
            for i, term in enumerate(sorted(list(prefixes_to_try_this_phase))): # Sort for consistent run order
                # generate_targeted_prefixes should already filter against attempted_search_terms
                # but we add it here after fetching to ensure it's marked for future generate_targeted_prefixes calls.
                
                print(f"\nProcessing refined term: '{term.strip()}' (sent as '{term}') ({i+1}/{len(prefixes_to_try_this_phase)} of current phase)...")
                brands_found_list = fetch_brands_for_term(term, session) # This is where the AJAX call happens
                attempted_search_terms.add(term) # Mark as attempted *after* trying
                
                if brands_found_list:
                    phase_newly_added_count = 0
                    for brand_info in brands_found_list:
                        name = brand_info.get("name")
                        if name:
                            if name not in all_brands_dict or \
                               (brand_info.get("id") is not None and all_brands_dict[name].get("id") is None):
                                all_brands_dict[name] = brand_info
                                phase_newly_added_count +=1
                    if phase_newly_added_count > 0:
                         print(f"  Added/Updated {phase_newly_added_count} brands for term '{term}'.")
                print(f"  Current total unique brands in dictionary: {len(all_brands_dict)}")
                time.sleep(0.1) # Keep a respectful delay
    
    # Save final results
    final_sorted_brands_list = sorted(list(all_brands_dict.values()), key=lambda x: x["name"].lower())
    actual_output_filename = Path.cwd() / output_filename
    with open(actual_output_filename, 'w', encoding='utf-8') as f:
        json.dump(final_sorted_brands_list, f, indent=2, ensure_ascii=False)
    
    print(f"\n--- Gap-Filling Process Complete ---")
    print(f"Found a total of {len(final_sorted_brands_list)} unique brands (started with {initial_brands_loaded_count}).")
    print(f"Saved to: {actual_output_filename}")
    print(f"Total search terms attempted in this run (including gap-filling): {len(attempted_search_terms)}")

    return final_sorted_brands_list


def analyze_brand_id_gaps(brand_filepath_str: str, max_id_gap_to_report_details: int = 5):
    """
    Loads a brand JSON file, sorts by ID, and reports on ID gaps,
    showing the names of the brands surrounding those gaps.

    Args:
        brand_filepath_str: Path to the JSON file containing the brand list.
                            Each item should be a dict with "name" and "id" keys.
        max_id_gap_to_report_details: Maximum number of missing IDs to list explicitly for a gap.
                                       If more IDs are missing, it will summarize.
                                       
    # --- How to Use ---
    1. Ensure the JSON file (e.g., "vintage_and_rare_brands_REFINED.json") is accessible.
    2. Set the path to your file in the line below.
    3. Run this script or paste the code into a Jupyter cell and call the function.

    Path to your final, refined brand list JSON file
    Make sure this path correctly points to your uploaded file.
    If the script/notebook is in the same directory as the JSON:
    final_brand_list_filepath = "vintage_and_rare_brands_REFINED.json" 
    Otherwise, provide the full absolute path:
    final_brand_list_filepath = "/path/to/your/vintage_and_rare_brands_REFINED.json"

    Run the analysis (uncomment the line below if running in a notebook cell)
    analyze_brand_id_gaps(final_brand_list_filepath)
    """
    brand_file = Path(brand_filepath_str)
    if not brand_file.is_file():
        print(f"Error: Brand file not found at '{brand_filepath_str}'")
        return

    print(f"--- Analyzing ID Gaps in: {brand_filepath_str} ---")
    try:
        with open(brand_file, 'r', encoding='utf-8') as f:
            brands_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from '{brand_filepath_str}'. {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred loading the file: {e}")
        return

    if not isinstance(brands_data, list):
        print("Error: Expected a list of brands from the JSON file.")
        return

    brands_with_numeric_ids = []
    brands_with_null_or_non_numeric_ids = 0
    for idx, brand in enumerate(brands_data):
        if not isinstance(brand, dict):
            print(f"Warning: Item at index {idx} is not a dictionary, skipping: {brand}")
            continue
        
        brand_id = brand.get("id")
        brand_name = brand.get("name", f"Unnamed Brand at index {idx}")

        if brand_id is None:
            brands_with_null_or_non_numeric_ids += 1
            continue 

        try:
            numeric_id = int(brand_id)
            brands_with_numeric_ids.append({"name": brand_name, "id": numeric_id})
        except (ValueError, TypeError):
            print(f"Warning: Brand '{brand_name}' has a non-convertible ID '{brand_id}', skipping.")
            brands_with_null_or_non_numeric_ids += 1
            continue
            
    if not brands_with_numeric_ids:
        print("No brands with valid numeric IDs found to analyze for gaps.")
        if brands_with_null_or_non_numeric_ids > 0:
            print(f"Note: {brands_with_null_or_non_numeric_ids} brands had null or non-numeric IDs and were excluded from gap analysis.")
        return

    # Sort brands by their numeric ID
    brands_sorted_by_id = sorted(brands_with_numeric_ids, key=lambda x: x["id"])

    print(f"\nFound {len(brands_sorted_by_id)} brands with numeric IDs (out of {len(brands_data)} total entries).")
    if brands_with_null_or_non_numeric_ids > 0:
        print(f"({brands_with_null_or_non_numeric_ids} brands had null or non-numeric IDs and were excluded from this gap analysis.)")
    
    print("Checking for ID gaps...")
    
    gaps_found_count = 0
    significant_gaps_details = [] # Store formatted strings for printing

    for i in range(len(brands_sorted_by_id) - 1):
        brand1 = brands_sorted_by_id[i]
        brand2 = brands_sorted_by_id[i+1]
        
        # Ensure IDs are indeed integers for subtraction
        id1 = brand1["id"]
        id2 = brand2["id"]
        
        id_diff = id2 - id1

        if id_diff > 1:
            gaps_found_count += 1
            missing_ids_count = id_diff - 1
            gap_detail_parts = [
                f"\nGap #{gaps_found_count} (Missing {missing_ids_count} ID(s)) found between:",
                f"  PREV: \"{brand1['name']}\" (ID: {id1})",
                f"  NEXT: \"{brand2['name']}\" (ID: {id2})"
            ]
            if missing_ids_count <= max_id_gap_to_report_details:
                gap_detail_parts.append(f"  Missing ID(s): {list(range(id1 + 1, id2))}")
            
            significant_gaps_details.append("\n".join(gap_detail_parts))
    
    if gaps_found_count == 0:
        print("\nCONCLUSION: No numeric ID gaps found (IDs are consecutive for entries with valid numeric IDs).")
    else:
        print(f"\nCONCLUSION: Found {gaps_found_count} instances of numeric ID gaps.")
        if significant_gaps_details:
            print("Details of gaps (listing up to specified missing ID details):")
            for detail in significant_gaps_details:
                print(detail)
        # This part might be redundant if all details are stored, or useful if details were truncated.
        # if len(significant_gaps_details) < gaps_found_count: 
        #     print(f"\n(Plus {gaps_found_count - len(significant_gaps_details)} more gaps, possibly with more than {max_id_gap_to_report_details} missing IDs each if not all were stored)")

    print("\n--- Analysis Finished ---")


if __name__ == "__main__":
    print("Starting V&R Brand Mining Script (Iterative Gap-Filling)...")
    
    vr_username = input("Enter your Vintage & Rare username: ")
    vr_password = getpass.getpass("Enter your Vintage & Rare password: ")

    if not vr_username or not vr_password:
        print("Username and password are required. Exiting.")
    else:
        # Ensure your previously generated JSON file is correctly named and in the CWD
        # or provide the full path to it.
        initial_file = "vintage_and_rare_brands_XY_space.json" 
        print(f"Will load initial brands from: {Path.cwd() / initial_file}")
        
        mined_brands = mine_all_vr_brands_iterative(
            vr_username, 
            vr_password,
            initial_brands_file=initial_file, # Make sure this file exists in CWD or provide full path
            output_filename="vintage_and_rare_brands_REFINED.json"
        )
        
        if mined_brands:
            print(f"\nTotal brands after refinement: {len(mined_brands)}")
            print("\nSample of first 30 refined brands (Name - ID):")
            for i, brand_info in enumerate(mined_brands[:30]):
                print(f"{i+1}. {brand_info['name']} - (ID: {brand_info.get('id', 'N/A')})")

