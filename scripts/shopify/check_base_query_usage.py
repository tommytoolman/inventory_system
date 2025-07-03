# scripts/check_base_query_usage.py
"""
Check if base_query_template is actually used anywhere in the client.
"""

def check_base_query_usage():
    """Check if base_query_template is referenced anywhere."""
    
    with open('app/services/shopify/client.py', 'r') as f:
        client_content = f.read()
    
    # Count references to base_query_template
    references = client_content.count('base_query_template')
    
    print(f"🔍 CHECKING base_query_template USAGE")
    print(f"=" * 50)
    print(f"References found: {references}")
    
    if references <= 1:  # Only the definition
        print(f"✅ base_query_template is NOT used - safe to remove")
        print(f"📝 You can delete the base_query_template variable")
    else:
        print(f"⚠️ base_query_template is used {references-1} times")
        
        # Show where it's used
        lines = client_content.split('\n')
        for i, line in enumerate(lines, 1):
            if 'base_query_template' in line and 'base_query_template =' not in line:
                print(f"   Line {i}: {line.strip()}")

if __name__ == "__main__":
    check_base_query_usage()