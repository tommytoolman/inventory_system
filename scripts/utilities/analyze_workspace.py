# First, let's analyze your current application structure and data models
import os
import sys
from pathlib import Path

def analyze_workspace_structure():
    """
    Analyze the current workspace to understand the application architecture.
    """
    print("🔍 ANALYZING WORKSPACE STRUCTURE")
    print("=" * 60)
    
    # Key directories to examine
    key_dirs = ['app', 'data', 'scripts', 'migrations', 'alembic']
    
    for dir_name in key_dirs:
        if os.path.exists(dir_name):
            print(f"\n📁 {dir_name}/")
            for root, dirs, files in os.walk(dir_name):
                level = root.replace(dir_name, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    if not file.startswith('.') and file.endswith(('.py', '.json', '.sql', '.ini')):
                        print(f"{subindent}{file}")
                if level > 2:  # Limit depth
                    break

def examine_app_structure():
    """
    Look specifically at the app directory structure to understand models, services, etc.
    """
    print("\n🏗️ APPLICATION ARCHITECTURE ANALYSIS")
    print("=" * 60)
    
    app_path = Path('app')
    if app_path.exists():
        for item in app_path.iterdir():
            if item.is_dir() and not item.name.startswith('__'):
                print(f"\n📂 app/{item.name}/")
                for subitem in item.iterdir():
                    if subitem.is_file() and subitem.suffix == '.py':
                        print(f"   📄 {subitem.name}")
                    elif subitem.is_dir() and not subitem.name.startswith('__'):
                        print(f"   📁 {subitem.name}/")

def check_existing_models():
    """
    Check for existing data models and database schema.
    """
    print("\n🗃️ CHECKING EXISTING DATA MODELS")
    print("=" * 60)
    
    # Look for models directory
    models_paths = [
        Path('app/models'),
        Path('app/core/models'), 
        Path('app/database/models'),
        Path('models')
    ]
    
    for models_path in models_paths:
        if models_path.exists():
            print(f"\n✅ Found models directory: {models_path}")
            for model_file in models_path.glob('*.py'):
                if model_file.name != '__init__.py':
                    print(f"   📄 {model_file.name}")
        else:
            print(f"❌ Not found: {models_path}")
    
    # Check for migration files
    migration_paths = [Path('migrations'), Path('alembic/versions')]
    for migration_path in migration_paths:
        if migration_path.exists():
            migration_files = list(migration_path.glob('*.py'))
            print(f"\n✅ Found {len(migration_files)} migration files in {migration_path}")

def check_existing_services():
    """
    Check for existing service layer architecture.
    """
    print("\n🔧 CHECKING EXISTING SERVICES")
    print("=" * 60)
    
    services_paths = [
        Path('app/services'),
        Path('app/core/services'),
        Path('services')
    ]
    
    for services_path in services_paths:
        if services_path.exists():
            print(f"\n✅ Found services directory: {services_path}")
            for service_item in services_path.iterdir():
                if service_item.is_dir() and not service_item.name.startswith('__'):
                    print(f"   📁 {service_item.name}/")
                    for service_file in service_item.glob('*.py'):
                        if service_file.name != '__init__.py':
                            print(f"      📄 {service_file.name}")
                elif service_item.suffix == '.py' and service_item.name != '__init__.py':
                    print(f"   📄 {service_item.name}")

# Run the analysis
def main():
    analyze_workspace_structure()
    examine_app_structure()
    check_existing_models()
    check_existing_services()

if __name__ == "__main__":
    main()