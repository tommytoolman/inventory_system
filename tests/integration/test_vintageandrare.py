import os
import sys
from pathlib import Path
import json
import pytest
from typing import Dict, List, Optional, Tuple
import subprocess
import itertools
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get absolute path to inventory_system and add to Python path
project_root = Path(__file__).resolve().parent.parent.parent.parent / 'inventory_system'
sys.path.insert(0, str(project_root))

# Debug print to verify paths
# print(f"Project root: {project_root}")
# print(f"sys.path: {sys.path}")  # Add this to see all import paths
# print(f"Category map path: {project_root / 'app' / 'services' / 'vintageandrare' / 'category_map.json'}")

# Now we can import using absolute imports
from tests.mocks import MockData
from tests.integration.media_handler import MediaHandler  # Changed to absolute import

class MandatoryFieldError(Exception):
    """Raised when a mandatory field is missing"""
    pass

class FormFieldValidator:
    """Validates form fields based on business rules"""
    
    MANDATORY_FIELDS = {
        'brand': 'Brand/Make is required',
        'model': 'Model name is required',
    }
    
    CONDITIONAL_MANDATORY = {
        'price': 'Price is required unless call_for_price is True',
        'subcategory': 'Subcategory is required for this category',
        'sub_subcategory': 'Sub-subcategory is required for this subcategory'
    }
    
    def __init__(self, category_map_path: Path):
        """Initialize with path to category mapping file"""
        with open(category_map_path) as f:
            self.category_map = json.load(f)
    
    def validate_fields(self, data: Dict) -> Tuple[bool, List[str]]:
        """Validate all fields based on business rules"""
        print(f"\nValidating fields for data: {data}")
        errors = []
        
        # Check mandatory fields
        for field, message in self.MANDATORY_FIELDS.items():
            if field not in data or not data[field]:
                print(f"Missing mandatory field: {field}")
                errors.append(message)
        
        # Check price/call_for_price logic
        if not data.get('call_for_price') and not data.get('price'):
            print("Missing price information")
            errors.append(self.CONDITIONAL_MANDATORY['price'])
        
        # Validate category hierarchy
        category_errors = self._validate_category_hierarchy(data)
        if category_errors:
            print(f"Category validation errors: {category_errors}")
        errors.extend(category_errors)
        
        if len(errors) > 0:
            print(f"Validation failed with errors: {errors}")
        else:
            print("Validation passed")
        
        return len(errors) == 0, errors
    
    def _validate_category_hierarchy(self, data: Dict) -> List[str]:
        """Validate category hierarchy based on category map"""
        errors = []
        category_id = data.get('category')
        
        print(f"\nValidating category hierarchy for data: {data}")  # Debug log
        
        if not category_id:
            print("No category_id found")  # Debug log
            errors.append("Main category is required")
            return errors
                
        # Check if category exists
        if category_id not in self.category_map:
            print(f"Category {category_id} not found in map")  # Debug log
            errors.append(f"Invalid category ID: {category_id}")
            return errors
                
        category_data = self.category_map[category_id]
        print(f"Found category data: {category_data}")  # Debug log
        
        # Check if subcategory is required
        if category_data['subcategories'] and not data.get('subcategory'):
            print(f"Subcategory required but not provided for category {category_id}")  # Debug log
            errors.append(f"Subcategory is required for category {category_id}")
            return errors
                
        # If subcategory is provided, validate it
        if subcategory_id := data.get('subcategory'):
            print(f"Checking subcategory: {subcategory_id}")  # Debug log
            if subcategory_id not in category_data['subcategories']:
                print(f"Invalid subcategory {subcategory_id}")  # Debug log
                errors.append(f"Invalid subcategory {subcategory_id} for category {category_id}")
                return errors
                    
            subcategory_data = category_data['subcategories'][subcategory_id]
            print(f"Found subcategory data: {subcategory_data}")  # Debug log
            
            # Check if sub-subcategory is required
            if subcategory_data['subcategories'] and not data.get('sub_subcategory'):
                print(f"Sub-subcategory required but not provided for subcategory {subcategory_id}")  # Debug log
                errors.append(f"Sub-subcategory is required for subcategory {subcategory_id}")
            
            # Validate sub-subcategory if provided
            if sub_subcategory_id := data.get('sub_subcategory'):
                print(f"Checking sub-subcategory: {sub_subcategory_id}")  # Debug log
                if sub_subcategory_id not in subcategory_data['subcategories']:
                    print(f"Invalid sub-subcategory {sub_subcategory_id}")  # Debug log
                    errors.append(f"Invalid sub-subcategory {sub_subcategory_id}")
        
        print(f"Validation complete. Errors: {errors}")  # Debug log
        return errors
    
    def _validate_shipping(self, data: Dict) -> List[str]:
        """Validate shipping-related fields"""
        errors = []
        
        if not any([
            data.get('europe_shipping'),
            data.get('usa_shipping'),
            data.get('uk_shipping'),
            data.get('world_shipping'),
            data.get('additional_shipping')
        ]):
            errors.append("At least one shipping option must be provided when shipping is enabled")
        
        return errors

class VintageAndRareTestCase:
    """Represents a test case for the V&R form"""
    
    def __init__(self, test_data: Dict, validator: FormFieldValidator):
        self.test_data = test_data
        self.validator = validator
        self.script_path = project_root / 'app' / 'services' / 'vintageandrare' / 'inspect_form.py'
    
    @property
    def command(self) -> List[str]:
        """Generate command line arguments for the test case"""
        cmd = [
            "python",
            str(self.script_path), 
                "--username", os.environ.get("VINTAGE_AND_RARE_USERNAME"), 
                "--password", os.environ.get("VINTAGE_AND_RARE_PASSWORD"), 
                "--test", "True"
        ]
        
        for key, value in self.test_data.items():
            if isinstance(value, bool):
                if value:
                    cmd.append(f"--{key}")
            elif isinstance(value, list):
                cmd.extend([f"--{key}"] + [str(v) for v in value])
            else:
                cmd.extend([f"--{key}", str(value)])
        
        return cmd
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate the test case data"""
        return self.validator.validate_fields(self.test_data)
    
    def run(self) -> Tuple[bool, Optional[str]]:
        """Run the test case and return (success, error_message)"""
        try:
            result = subprocess.run(
                self.command,
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode == 0, result.stderr if result.returncode != 0 else None
            
        except subprocess.TimeoutExpired:
            return False, "Test case timed out"
        except Exception as e:
            return False, str(e)

class TestCaseGenerator:
    """Generates test cases for V&R form testing"""
    
    def __init__(self, category_map_path: Path):
        """Initialize with category map path"""
        self.validator = FormFieldValidator(category_map_path)
        # Get access to the category map from the validator
        self.category_map = self.validator.category_map
        # Initialize other needed properties
        self.test_images_dir = project_root / 'tests' / 'mocks' / 'images'
        self.test_videos_dir = project_root / 'tests' / 'mocks' / 'videos'
    
    @staticmethod
    def create(category_map_path: Path) -> 'TestCaseGenerator':
        """Factory method to create TestCaseGenerator instance"""
        generator = TestCaseGenerator()
        generator.validator = FormFieldValidator(category_map_path)
        return generator
        self.validator = FormFieldValidator(category_map_path)
        
        # Load test resources
        self.test_images_dir = project_root / 'tests' / 'mocks' / 'images'
        self.test_videos_dir = project_root / 'tests' / 'mocks' / 'videos'
    
    def generate_category_combinations(self) -> List[Dict]:
        """Generate valid category combinations based on the map"""
        combinations = []
        print("\nGenerating category combinations...")  # Debug log
        
        for main_id, main_data in self.category_map.items():
            print(f"\nProcessing main category: {main_id}")  # Debug log
            
            # Test main category alone if it doesn't require subcategories
            if not main_data['subcategories']:
                print(f"No subcategories required for {main_id}")  # Debug log
                combinations.append({'category': main_id})
                continue
            
            # Test with subcategories
            print(f"Processing subcategories for {main_id}")  # Debug log
            for sub_id, sub_data in main_data['subcategories'].items():
                print(f"Processing subcategory: {sub_id}")  # Debug log
                
                # Test main + sub combination
                if not sub_data['subcategories']:
                    print(f"No sub-subcategories for {sub_id}")  # Debug log
                    combinations.append({
                        'category': main_id,
                        'subcategory': sub_id
                    })
                    continue
                
                # Test with sub-subcategories
                print(f"Processing sub-subcategories for {sub_id}")  # Debug log
                for subsub_id in sub_data['subcategories']:
                    print(f"Adding combination with sub-subcategory: {subsub_id}")  # Debug log
                    combinations.append({
                        'category': main_id,
                        'subcategory': sub_id,
                        'sub_subcategory': subsub_id
                    })
        
        print(f"\nGenerated {len(combinations)} category combinations")  # Debug log
        print(f"Combinations: {combinations}")  # Debug log
        return combinations
    
    # def generate_test_cases(self) -> List[VintageAndRareTestCase]:
    #     """Generate comprehensive test cases with a reasonable limit"""
    #     print("Starting to generate test cases...")
    #     test_cases = []
    #     max_test_cases = 50  # Reasonable limit
        
    #     base_data = {
    #         'brand': 'Fender',
    #         'model': 'Test Model',
    #         'year': '1964',
    #         'color': 'Sunburst',
    #         'description': 'Test description',
    #         'processing_time': '3',
    #         'time_unit': 'Days'
    #     }
        
    #     category_combos = list(self.generate_category_combinations())
    #     price_combos = list(self._generate_price_combinations())
    #     shipping_combos = list(self._generate_shipping_combinations())
    #     media_combos = list(self._generate_media_combinations())
        
    #     print(f"Generated combinations:")
    #     print(f"Categories: {len(category_combos)}")
    #     print(f"Prices: {len(price_combos)}")
    #     print(f"Shipping: {len(shipping_combos)}")
    #     print(f"Media: {len(media_combos)}")
        
    #     test_case_count = 0
    #     for category_combo in category_combos:
    #         if test_case_count >= max_test_cases:
    #             break
                
    #         for price_combo in price_combos:
    #             if test_case_count >= max_test_cases:
    #                 break
                    
    #             for shipping_combo in shipping_combos:
    #                 if test_case_count >= max_test_cases:
    #                     break
                        
    #                 for media_combo in media_combos:
    #                     if test_case_count >= max_test_cases:
    #                         break
                            
    #                     test_data = {
    #                         **base_data,
    #                         **category_combo,
    #                         **price_combo,
    #                         **shipping_combo,
    #                         **media_combo
    #                     }
                        
    #                     test_case = VintageAndRareTestCase(test_data, self.validator)
    #                     is_valid, _ = test_case.validate()
                        
    #                     if is_valid:
    #                         test_cases.append(test_case)
    #                         test_case_count += 1
    #                         print(f"Generated test case {test_case_count}/{max_test_cases}")
        
    #     print(f"Final number of valid test cases: {len(test_cases)}")
    #     return test_cases
    
    def generate_test_cases(self) -> List[VintageAndRareTestCase]:
        """Generate comprehensive test cases"""
        print("\n=== Starting Test Case Generation ===")
        
        # First, let's see what our category map looks like
        print("\nCategory Map Structure:")
        print(json.dumps(self.category_map, indent=2))
        
        test_cases = []
        base_data = {
            'brand': 'Fender',
            'model': 'Test Model',
            'year': '1964',
            'color': 'Sunburst',
            'description': 'Test description',
            'processing_time': '3',
            'time_unit': 'Days'
        }
        
        # Get all combinations but print them first
        print("\nGenerating Combinations:")
        category_combos = list(self.generate_category_combinations())
        print(f"\nCategory Combinations ({len(category_combos)}):")
        for combo in category_combos:
            print(f"  {combo}")
        
        price_combos = list(self._generate_price_combinations())
        print(f"\nPrice Combinations ({len(price_combos)}):")
        for combo in price_combos:
            print(f"  {combo}")
        
        shipping_combos = list(self._generate_shipping_combinations())
        print(f"\nShipping Combinations ({len(shipping_combos)}):")
        for combo in shipping_combos:
            print(f"  {combo}")
        
        print("\nStarting combination loop...")
        combination_count = 0
        
        # Add a counter to prevent infinite loops
        MAX_COMBINATIONS = 1000
        
        for category_combo in category_combos:
            print(f"\nTrying category combo: {category_combo}")
            
            for price_combo in price_combos:
                print(f"  With price combo: {price_combo}")
                
                for shipping_combo in shipping_combos:
                    combination_count += 1
                    if combination_count > MAX_COMBINATIONS:
                        print("WARNING: Hit maximum combination limit!")
                        return test_cases
                    
                    print(f"    Testing combination {combination_count}")
                    
                    test_data = {
                        **base_data,
                        **category_combo,
                        **price_combo,
                        **shipping_combo
                    }
                    
                    # Create and validate test case
                    test_case = VintageAndRareTestCase(test_data, self.validator)
                    is_valid, errors = test_case.validate()
                    
                    if not is_valid:
                        print(f"      Invalid combination: {errors}")
                        continue
                    
                    print(f"      Valid combination found!")
                    test_cases.append(test_case)
        
        print(f"\nFinal number of valid test cases: {len(test_cases)}")
        return test_cases
    
    
    def _generate_price_combinations(self) -> List[Dict]:
        """Generate valid price combinations"""
        return [
            {'price': '1500'},
            {'price': '1500', 'show_vat': True},
            {'price': '1500', 'discounted_price': '1200'},
            {'call_for_price': True},
            {'price': '1500', 'buy_it_now': True}
        ]
    
    def _generate_shipping_combinations(self) -> List[Dict]:
        """Generate valid shipping combinations"""
        base_shipping = {'shipping': True}
        
        # Limit the number of combinations to something reasonable
        combinations = []
        regions = ['europe', 'usa', 'uk', 'world']
        fees = ['50', '100', '150', '200']
        
        # Generate a smaller, fixed set of common shipping scenarios
        combinations = [
            # Single region shipping options
            {**base_shipping, 'europe_shipping': '50'},
            {**base_shipping, 'usa_shipping': '100'},
            {**base_shipping, 'uk_shipping': '75'},
            {**base_shipping, 'world_shipping': '150'},
            
            # Common multi-region combinations
            {**base_shipping, 'europe_shipping': '50', 'uk_shipping': '75'},
            {**base_shipping, 'usa_shipping': '100', 'world_shipping': '150'},
            
            # One with additional shipping
            {**base_shipping, 'europe_shipping': '50', 'usa_shipping': '100', 
            'additional_shipping': ['Japan:250', 'Australia:275']},
        ]
        
        return combinations
    
    def _generate_media_combinations(self) -> List[Dict]:
        """Generate media upload combinations including URLs"""
        # Sample image and video URLs (replace with your actual test URLs)
        test_image_urls = [
            'https://example.com/test1.jpg',
            'https://example.com/test2.jpg'
        ]
        
        test_video_urls = [
            'https://youtube.com/watch?v=example1',
            'https://youtube.com/watch?v=example2'
        ]
        
        combinations = [{}]  # Start with no media
        
        # Image combinations
        if test_image_urls:
            with MediaHandler() as handler:
                # Test single image
                single_image = handler.download_image(test_image_urls[0])
                if single_image:
                    combinations.append({'images': [str(single_image)]})
                
                # Test multiple images
                multiple_images = [handler.download_image(url) for url in test_image_urls[:2]]
                if all(multiple_images):
                    combinations.append({'images': [str(img) for img in multiple_images]})
        
        # Video URL combinations
        combinations.extend([
            {'youtube': url} for url in test_video_urls[:2]
        ])
        
        # Combine images and videos
        if test_image_urls and test_video_urls:
            with MediaHandler() as handler:
                if image := handler.download_image(test_image_urls[0]):
                    combinations.append({
                        'images': [str(image)],
                        'youtube': test_video_urls[0]
                    })
        
        return combinations

@pytest.mark.integration
def test_vintage_and_rare_form():
    """Integration test for V&R form submission"""
    category_map_path = project_root / 'app' / 'services' / 'vintageandrare' / 'category_map.json'

    # Initialize test case generator
    generator = TestCaseGenerator(category_map_path)

    # Generate and run test cases
    test_cases = generator.generate_test_cases()
    results = []

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nRunning test case {i}/{len(test_cases)}")
        
        # Run the test
        success, error = test_case.run()
        
        # Record result
        results.append({
            'test_case': i,
            'data': test_case.test_data,
            'success': success,
            'error': error
        })
        
        # Save interim results
        results_path = project_root / 'tests' / 'integration' / 'results' / 'vintageandrare_results.json'
        results_path.parent.mkdir(exist_ok=True)
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        time.sleep(2)  # Brief pause between tests
    
    # Print summary
    successful = sum(1 for r in results if r['success'])
    print(f"\nTest Summary:")
    print(f"Total test cases: {len(test_cases)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(test_cases) - successful}")
    print(f"\nDetailed results saved to {results_path}")
    
    # Assert all tests passed
    assert successful == len(test_cases), f"{len(test_cases) - successful} test cases failed"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])