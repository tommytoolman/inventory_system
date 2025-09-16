#!/bin/bash

# Import data to Railway database
# Usage: ./scripts/import_to_railway.sh

echo "🚀 Railway Data Import Script"
echo "============================"
echo ""
echo "Please get your Railway database URL from:"
echo "1. Go to your Railway dashboard"
echo "2. Click on your Postgres service"
echo "3. Go to the Variables tab"
echo "4. Copy the DATABASE_URL value"
echo ""
echo "The URL should look like:"
echo "postgresql://postgres:KrRdFYWqBowSaMDzBLqIdoUxQXkdycJf@postgres.railway.internal:5432/railway"
echo ""
read -p "Please paste your Railway DATABASE_URL: " RAILWAY_DB_URL

if [ -z "$RAILWAY_DB_URL" ]; then
    echo "❌ No database URL provided. Exiting."
    exit 1
fi

# Activate virtual environment
echo ""
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Run the import
echo ""
echo "📦 Starting import..."
python scripts/import_data.py --db-url "$RAILWAY_DB_URL"

echo ""
echo "✅ Import process complete!"