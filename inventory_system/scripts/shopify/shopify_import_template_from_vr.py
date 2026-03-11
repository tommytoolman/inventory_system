import pandas as pd
import re
   
def generate_shopify_handle(brand, model_name, product_id):
    """Generates a URL-friendly handle."""
    text = f"{brand} {model_name} {product_id}"
    text = text.lower()
    text = re.sub(r'\s+', '-', text)  # Replace spaces with hyphens
    text = re.sub(r'[^a-z0-9\-]', '', text)  # Remove non-alphanumeric characters except hyphens
    return text[:255] 

def map_vr_category_to_shopify_product_category(vr_category_name):
    """Maps Vintage & Rare category to Shopify's Standard Product Category."""
    # Base path for most musical instruments
    base_path = "Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments"

    if not isinstance(vr_category_name, str):
        return f"{base_path} > Guitars" # Default if category is not a string (e.g., NaN)

    lower_cat = vr_category_name.lower()

    # Guitars
    if "guitar" in lower_cat:
        if "bass" in lower_cat: # Specifically bass guitars
            return f"{base_path} > String Instruments > Basses"
        elif "archtop" in lower_cat:
            return f"{base_path} > String Instruments > Guitars" # Could add sub-category if Shopify supports Archtop specifically
        elif "semi-hollow" in lower_cat:
            return f"{base_path} > String Instruments > Guitars" # Could add sub-category
        elif "flat top" in lower_cat or "acoustic" in lower_cat : # Acoustic Guitars often have flat tops
             if "12 string" in lower_cat:
                return f"{base_path} > String Instruments > Acoustic Guitars" # Or a specific 12-string acoustic if available
             return f"{base_path} > String Instruments > Acoustic Guitars"
        elif "electric solid body" in lower_cat or "chambered solid body" in lower_cat:
            if "12 string" in lower_cat:
                 return f"{base_path} > String Instruments > Electric Guitars" # Or specific 12-string electric
            return f"{base_path} > String Instruments > Electric Guitars"
        elif "resonator" in lower_cat:
            return f"{base_path} > String Instruments > Resonator Guitars"
        elif "gypsy jazz" in lower_cat:
            return f"{base_path} > String Instruments > Acoustic Guitars" # Often a type of acoustic
        elif "tenor" in lower_cat:
            return f"{base_path} > String Instruments > Guitars" # General, or could be Acoustic/Electric
        return f"{base_path} > String Instruments > Guitars" # General Guitars fallback

    # Basses (if not caught by "guitar" in lower_cat and "bass" in lower_cat)
    elif "basses" in lower_cat:
        return f"{base_path} > String Instruments > Basses"

    # Amplifiers
    elif "amps" in lower_cat or "amplifiers" in lower_cat:
        if "heads" in lower_cat and "cab" in lower_cat: # Head + Cab
             return f"{base_path} > Amplifiers" # General Amps, or could be split
        elif "heads" in lower_cat:
            return f"{base_path} > Instrument Accessories > Amplifier Accessories > Amplifier Heads"
        elif "combo" in lower_cat:
            return f"{base_path} > Amplifiers" # Or specifically Guitar Amplifiers / Bass Amplifiers if distinguishable
        elif "cabinets" in lower_cat:
            return f"{base_path} > Instrument Accessories > Amplifier Accessories > Amplifier Cabinets"
        return f"{base_path} > Amplifiers"

    # Effects Pedals
    elif "effects" in lower_cat or "pedals" in lower_cat: # Assuming "pedals" implies effects pedals
        if "fuzz" in lower_cat and "distortion" in lower_cat: # Fuzz/Distortion
             return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Distortion & Overdrive Pedals"
        elif "fuzz" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Fuzz Pedals"
        elif "treble booster" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories" # General effects accessory
        elif "wah" in lower_cat: # Wah Wah
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Wah Pedals"
        elif "multieffect" in lower_cat: # Multieffect
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Multi-Effects Pedals"
        elif "octave" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Pitch Shifter & Octave Pedals"
        elif "chorus" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Chorus Pedals"
        elif "compressor" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Compressor & Sustainer Pedals"
        elif "looper" in lower_cat or "switching" in lower_cat or "controller" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Looper Pedals" # Or general accessory
        elif "reverb" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Reverb Pedals"
        elif "delay" in lower_cat or "echo" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Delay Pedals"
        elif "overdrive" in lower_cat:
            return f"{base_path} > Instrument Accessories > Effects Pedal Accessories > Distortion & Overdrive Pedals"
        return f"{base_path} > Effects Pedals" # General Effects Pedals if not more specific

    # Pianos, Synths & Keyboards
    elif "pianos" in lower_cat or "keyboard" in lower_cat:
        if "grand piano" in lower_cat:
            return f"{base_path} > Keyboards & Pianos > Acoustic Pianos" # Or Grand Pianos if exists
        elif "synth" in lower_cat:
            return f"{base_path} > Keyboards & Pianos > Synthesizers"
        return f"{base_path} > Keyboards & Pianos"

    # Drums
    elif "drums" in lower_cat:
        if "shell kits" in lower_cat:
            return f"{base_path} > Drums & Percussion > Drum Sets"
        return f"{base_path} > Drums & Percussion"

    # Other Stringed Instruments
    elif "stringed instruments" in lower_cat:
        if "mandolin" in lower_cat:
            return f"{base_path} > String Instruments > Mandolins"
        return f"{base_path} > String Instruments" # General string instruments

    # Fallbacks
    return base_path # General "Musical Instruments" if no specific match

def get_merchant_defined_type(vr_category_name):
    """Extracts a merchant-defined type from the V&R category string."""
    if not isinstance(vr_category_name, str):
        return "Unknown"
    parts = vr_category_name.split('>')
    # Return the most specific part, or the whole string if no '>'
    return parts[-1].strip() if parts else vr_category_name.strip()


def main():
    # Load the vintage and rare inventory CSV - UPDATED FILENAME
    try:
        vr_df = pd.read_csv("scripts/data/vintageandrare_inventory_2025-06-02_08-08.csv")
        print(f"Successfully loaded: vintageandrare_inventory_2025-06-02_08-08.csv")
    except Exception as e:
        print(f"Error loading vintageandrare_inventory_2025-06-02_08-08.csv: {e}")
        return

    # Load the Shopify product template to get column names
    try:
        # Assuming the template file name remains the same or you update it if needed
        shopify_template_df = pd.read_csv("scripts/data/product_template_290525.csv")
        shopify_columns = list(shopify_template_df.columns)
        print(f"Successfully loaded Shopify template: product_template_290525.csv")
    except Exception as e:
        print(f"Error loading product_template_290525.csv: {e}")
        return

    output_rows = []

    for index, row in vr_df.iterrows():
        is_sold = str(row.get('product sold', 'yes')).strip().lower() == 'yes'
        is_in_inventory = str(row.get('product in inventory', 'no')).strip().lower() == 'yes'

        # Only process items that are NOT sold AND are in inventory for active listings
        # Or, if you want to upload all items and manage status later, adjust this logic
        published_status = 'TRUE' if not is_sold and is_in_inventory else 'FALSE'
        shopify_status = 'active' if published_status == 'TRUE' else 'draft'

        handle = generate_shopify_handle(str(row.get('brand name', '')),
                                        str(row.get('product model name', '')),
                                        str(row.get('product id', index)))

        title_year_part = ""
        if pd.notna(row.get('product year')):
            try:
                # Convert to int then str to remove ".0"
                title_year_part = str(int(float(row.get('product year')))) + " "
            except ValueError: 
                title_year_part = str(row.get('product year')).strip() + " "


        title = f"{title_year_part}{str(row.get('brand name', '')).strip()} {str(row.get('product model name', '')).strip()}".strip()
        body_html = str(row.get('product description', ''))
        vendor = str(row.get('brand name', '')).strip()
        
        vr_cat_name = row.get('category name', '')
        shopify_product_category = map_vr_category_to_shopify_product_category(vr_cat_name)
        merchant_type = get_merchant_defined_type(vr_cat_name)

        tags_list = []
        if vendor: tags_list.append(vendor)
        if merchant_type and merchant_type != "Unknown": tags_list.append(merchant_type)
        if pd.notna(row.get('product finish')) and str(row.get('product finish')).strip():
             tags_list.append(str(row.get('product finish')).strip())
        if title_year_part.strip(): # Add year as a tag if present
             tags_list.append(title_year_part.strip())
        
        tags = ", ".join(filter(None, tags_list))


        option1_name = "Title" 
        option1_value = "Default Title" 

        variant_sku = str(row.get('product id', f'sku-{index}'))
        variant_price = row.get('product price', 0.0)
        
        image_urls_str = str(row.get('image url', ''))
        image_urls = [url.strip() for url in image_urls_str.split('|') if url.strip()]
        main_image_src = image_urls[0] if image_urls else ""

        shopify_row = {col: "" for col in shopify_columns} 

        shopify_row.update({
            "Handle": handle,
            "Title": title,
            "Body (HTML)": body_html,
            "Vendor": vendor,
            "Product Category": shopify_product_category,
            "Type": merchant_type,
            "Tags": tags,
            "Published": published_status,
            "Option1 Name": option1_name,
            "Option1 Value": option1_value,
            "Variant SKU": variant_sku,
            "Variant Price": variant_price,
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "TRUE", 
            "Image Src": main_image_src,
            "Image Position": 1 if main_image_src else "",
            "Gift Card": "FALSE",
            "Status": shopify_status,
            "Variant Inventory Tracker": "", # Shopify manages this based on settings or if Qty is set
            "Variant Inventory Qty": 1 if is_in_inventory and not is_sold else 0, # Basic default
            # Ensure SEO description is plain text and reasonably short
            "SEO Title": title[:70], 
            "SEO Description": re.sub('<[^<]+?>', '', str(body_html)).replace('\n', ' ').strip()[:320],
        })
        output_rows.append(shopify_row)

        if len(image_urls) > 1:
            for i, img_url in enumerate(image_urls[1:], start=2): 
                image_row_data = {
                    "Handle": handle,
                    "Image Src": img_url,
                    "Image Position": i,
                }
                full_image_row = {col: "" for col in shopify_columns}
                full_image_row.update(image_row_data)
                output_rows.append(full_image_row)

    output_df = pd.DataFrame(output_rows, columns=shopify_columns)
    
    # UPDATED OUTPUT FILENAME (optional, but good practice for new input)
    output_filename = "scripts/data/shopify_import_from_vr_new.csv" 
    try:
        output_df.to_csv(output_filename, index=False)
        print(f"\nSuccessfully created {output_filename}")
    except Exception as e:
        print(f"Error writing output CSV: {e}")

if __name__ == "__main__":
    main() 