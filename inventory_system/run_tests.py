#!/usr/bin/env python3
"""
run_tests.py - Run pytest with output saved to file

Usage:
    python run_tests.py
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def setup_environment():
    """Set up required environment variables for tests."""
    os.environ["SECRET_KEY"] = "test"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

    # eBay — dummy values so SecureTokenManager.__init__ doesn't raise
    os.environ.setdefault("EBAY_REFRESH_TOKEN", "test_ebay_refresh_token")
    os.environ.setdefault("EBAY_CLIENT_ID", "test_ebay_client_id")
    os.environ.setdefault("EBAY_CLIENT_SECRET", "test_ebay_client_secret")
    os.environ.setdefault("EBAY_SANDBOX_REFRESH_TOKEN", "test_ebay_sandbox_refresh_token")
    os.environ.setdefault("EBAY_SANDBOX_CLIENT_ID", "test_ebay_sandbox_client_id")
    os.environ.setdefault("EBAY_SANDBOX_CLIENT_SECRET", "test_ebay_sandbox_client_secret")

    # Reverb — dummy value
    os.environ.setdefault("REVERB_API_KEY", "test_reverb_api_key")

    # VintageAndRare — dummy values
    os.environ.setdefault("VR_USERNAME", "test_vr_user")
    os.environ.setdefault("VR_PASSWORD", "test_vr_pass")

    print("✓ Environment variables set:")
    print(f"  SECRET_KEY = {os.environ['SECRET_KEY']}")
    print(f"  DATABASE_URL = {os.environ['DATABASE_URL']}")
    print("  EBAY_REFRESH_TOKEN = (dummy test value)")
    print("  REVERB_API_KEY = (dummy test value)")
    print()


def create_output_directory():
    """Create test_results directory if it doesn't exist."""
    output_dir = Path("test_results")
    output_dir.mkdir(exist_ok=True)
    return output_dir


def generate_log_filename(output_dir):
    """Generate unique log filename with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = output_dir / f"test_results_{timestamp}.txt"
    summary_file = output_dir / f"test_summary_{timestamp}.txt"
    return log_file, summary_file, timestamp


def run_pytest(log_file):
    """Run pytest with proper arguments and capture output."""
    pytest_args = [
        "python",
        "-m",
        "pytest",
        "tests/",
        "-q",
        "--ignore=tests/unit/test_ebay_item_specifics.py",
        "--ignore=tests/integration",
        "-m",
        "not integration",
        "--cov=app",
        "--cov-report=term",
        "--tb=short",
        "-v",
    ]

    print("Running pytest...")
    print(f"Output will be saved to: {log_file}")
    print()
    print("-" * 80)
    print()

    with open(log_file, "w", encoding="utf-8") as f:
        process = subprocess.Popen(
            pytest_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )

        for line in process.stdout:
            print(line, end="")
            f.write(line)

        process.wait()
        return_code = process.returncode

    return return_code


def create_summary(summary_file, timestamp, log_file, return_code):
    """Create a summary file with test run information."""
    status = "✓ PASSED" if return_code == 0 else "✗ FAILED"

    summary_content = f"""TEST RUN SUMMARY
================

Timestamp: {timestamp}
Status: {status}
Return Code: {return_code}

Files Generated:
  - Test Results: {log_file}
  - Summary: {summary_file}

To view full results:
  1. Open {log_file} in your text editor
  2. All test output is preserved in this file
  3. No output has been truncated

Test Command Used:
  python -m pytest tests/ -q \\
    --ignore=tests/unit/test_ebay_item_specifics.py \\
    --ignore=tests/integration \\
    -m "not integration" \\
    --cov=app \\
    --cov-report=term \\
    --tb=short \\
    -v

Environment Variables:
  SECRET_KEY: test
  DATABASE_URL: sqlite+aiosqlite:///:memory:
  EBAY_REFRESH_TOKEN: (dummy)
  REVERB_API_KEY: (dummy)

Next Steps:
  1. Review test results in {log_file}
  2. If all tests pass, you're ready to push to production
  3. If there are failures, check the error messages for details
"""

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(summary_content)


def display_summary_info(log_file, summary_file, return_code):
    """Display summary information to console."""
    print()
    print("-" * 80)
    print()
    print("Test run completed!")
    print()
    print("📄 Results saved to:")
    print(f"   • {log_file}")
    print(f"   • {summary_file}")
    print()

    if return_code == 0:
        print("✅ All tests passed!")
    else:
        print(f"⚠️  Some tests failed (exit code: {return_code})")
        print("   Check the output file for details")
    print()
    print("To view results in your text editor:")
    print(f"   code {log_file}")
    print()


def parse_test_results(log_file):
    """Parse test results from log file and display summary."""
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        for line in reversed(lines):
            if "passed" in line or "failed" in line:
                print("Test Summary:")
                print(f"   {line.strip()}")
                break
    except Exception as e:
        print(f"Note: Could not parse test summary ({e})")


def main():
    """Main entry point."""
    print()
    print("=" * 80)
    print("RIFF Phase 1 Test Runner")
    print("=" * 80)
    print()

    setup_environment()
    output_dir = create_output_directory()
    log_file, summary_file, timestamp = generate_log_filename(output_dir)

    return_code = run_pytest(log_file)

    create_summary(summary_file, timestamp, log_file, return_code)
    display_summary_info(log_file, summary_file, return_code)
    parse_test_results(log_file)

    sys.exit(return_code)


if __name__ == "__main__":
    main()
