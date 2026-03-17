# run_tests.ps1 - Run pytest with required environment variables

# Set environment variables
$env:SECRET_KEY = "test"
$env:DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Run pytest with the required environment variables
python -m pytest tests/ -q `
  --ignore=tests/unit/test_ebay_item_specifics.py `
  --ignore=tests/integration `
  -m "not integration" `
  --cov=app `
  --cov-report=term

Write-Host "`nTests completed. Press Enter to exit."
Read-Host